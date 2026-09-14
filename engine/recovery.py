"""Recovery — reach a target that is not immediately resolvable.

Bounded escalation, in order:

    1. resolve now (selectors)
    2. wait / retry (screen may still be settling)
    3. dismiss a blocking keyboard, retry
    4. scroll into view, retry each pass
    5. OCR fallback (last resort)

Every attempt is recorded on a :class:`RecoveryTrace`. If nothing reaches the
target, returns ``(None, trace)`` and the caller reports BLOCKED. This is the
"recovers when a target is not immediately reachable" behaviour from the brief.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .config import (
    RECOVERY_MAX_RETRIES,
    RECOVERY_MAX_SCROLLS,
    RECOVERY_RETRY_WAIT_S,
)
from .device import Device
from .models import RecoveryTrace, ResolutionResult
from . import resolver as resolver_mod


def reach(d: Device, target: dict[str, Any],
          sleep=time.sleep) -> tuple[Optional[ResolutionResult], RecoveryTrace]:
    """Try hard to resolve ``target``. Returns (ResolutionResult|None, trace).

    ``sleep`` is injectable so tests run without real delays.
    """
    trace = RecoveryTrace()

    # 1. immediate (selectors only — OCR is saved for the final stage)
    res = resolver_mod.resolve(d, target, allow_ocr=False)
    if res.found:
        trace.record("immediate", "resolved", res.strategy or "")
        return res, trace
    trace.record("immediate", "not_found")

    # 2. wait / retry
    for attempt in range(1, RECOVERY_MAX_RETRIES + 1):
        sleep(RECOVERY_RETRY_WAIT_S)
        res = resolver_mod.resolve(d, target, allow_ocr=False)
        if res.found:
            trace.record("retry", "resolved", f"attempt {attempt} via {res.strategy}")
            return res, trace
        trace.record("retry", "not_found", f"attempt {attempt}")

    # 3. dismiss keyboard if it's covering the target
    if _safe(d.keyboard_visible):
        try:
            d.press_back()
            trace.record("dismiss_keyboard", "pressed_back")
        except Exception as exc:
            trace.record("dismiss_keyboard", "error", str(exc))
        res = resolver_mod.resolve(d, target, allow_ocr=False)
        if res.found:
            trace.record("post_keyboard", "resolved", res.strategy or "")
            return res, trace
        trace.record("post_keyboard", "not_found")

    # 4. scroll into view
    for i in range(1, RECOVERY_MAX_SCROLLS + 1):
        try:
            d.scroll_forward()
            trace.record("scroll", "forward", f"pass {i}")
        except Exception as exc:
            trace.record("scroll", "error", str(exc))
            break
        res = resolver_mod.resolve(d, target, allow_ocr=False)
        if res.found:
            trace.record("post_scroll", "resolved", f"pass {i} via {res.strategy}")
            return res, trace
        trace.record("post_scroll", "not_found", f"pass {i}")

    # 5. OCR fallback (last resort)
    res = resolver_mod.resolve(d, target, allow_ocr=True)
    if res.found:
        trace.record("ocr", "resolved", f"confidence {round(res.confidence, 3)}")
        return res, trace
    trace.record("ocr", "not_found")

    return None, trace


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
