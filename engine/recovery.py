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
from . import inspect as inspect_mod
from . import resolver as resolver_mod

# Buttons that dismiss a blocking system/permission dialog, in order.
_DISMISS_LABELS = ("Allow", "While using the app", "Only this time", "OK",
                   "Continue", "Got it", "Accept")


def _tap(d: Device, res: ResolutionResult) -> None:
    if res.element is not None:
        res.element.click()
    elif res.coordinates:
        d.tap_xy(*res.coordinates)


def reach(d: Device, target: dict[str, Any],
          sleep=time.sleep, *, role: str = "tappable",
          cache=None) -> tuple[Optional[ResolutionResult], RecoveryTrace]:
    """Try hard to resolve ``target``. Returns (ResolutionResult|None, trace).

    ``role``/``cache`` thread into the resolver so recovery re-perceives and
    re-resolves on the same shared model (selectors → cache → ranking → OCR).
    ``sleep`` is injectable so tests run without real delays.
    """
    trace = RecoveryTrace()

    def _resolve(allow_ocr: bool):
        return resolver_mod.resolve(d, target, allow_ocr=allow_ocr, role=role, cache=cache)

    # 1. immediate (selectors/cache/ranking — OCR is saved for the final stage)
    res = _resolve(False)
    if res.found:
        trace.record("immediate", "resolved", res.strategy or "")
        return res, trace
    trace.record("immediate", "not_found")

    # 2. wait / retry
    previous_screen = _screen_signature(d)
    for attempt in range(1, RECOVERY_MAX_RETRIES + 1):
        sleep(RECOVERY_RETRY_WAIT_S)
        res = _resolve(False)
        if res.found:
            trace.record("retry", "resolved", f"attempt {attempt} via {res.strategy}")
            return res, trace
        trace.record("retry", "not_found", f"attempt {attempt}")
        current_screen = _screen_signature(d)
        if current_screen and current_screen == previous_screen:
            trace.record("retry", "skipped", "screen unchanged; escalating")
            break
        previous_screen = current_screen or previous_screen

    # 3. dismiss keyboard if it's covering the target
    if _safe(d.keyboard_visible):
        try:
            d.press_back()
            trace.record("dismiss_keyboard", "pressed_back")
        except Exception as exc:
            trace.record("dismiss_keyboard", "error", str(exc))
        res = _resolve(False)
        if res.found:
            trace.record("post_keyboard", "resolved", res.strategy or "")
            return res, trace
        trace.record("post_keyboard", "not_found")

    # 3.5 dismiss a blocking dialog / permission overlay, then re-resolve
    try:
        els = inspect_mod.parse_elements(d.dump_hierarchy())
    except Exception:
        els = []
    if inspect_mod.window_flags(els).get("dialog"):
        dismissed = False
        for label in _DISMISS_LABELS:
            r = resolver_mod.resolve(d, {"label": label}, allow_ocr=False,
                                     role="tappable")
            if r.found:
                _tap(d, r)
                trace.record("dismiss_dialog", "tapped", label)
                dismissed = True
                break
        if not dismissed:
            try:
                d.press_back()
                trace.record("dismiss_dialog", "back")
            except Exception as exc:
                trace.record("dismiss_dialog", "error", str(exc))
        res = _resolve(False)
        if res.found:
            trace.record("post_dialog", "resolved", res.strategy or "")
            return res, trace
        trace.record("post_dialog", "not_found")

    # 4. scroll into view
    previous_screen = _screen_signature(d)
    for i in range(1, RECOVERY_MAX_SCROLLS + 1):
        try:
            d.scroll_forward()
            trace.record("scroll", "forward", f"pass {i}")
        except Exception as exc:
            trace.record("scroll", "error", str(exc))
            break
        res = _resolve(False)
        if res.found:
            trace.record("post_scroll", "resolved", f"pass {i} via {res.strategy}")
            return res, trace
        trace.record("post_scroll", "not_found", f"pass {i}")
        current_screen = _screen_signature(d)
        if current_screen and current_screen == previous_screen:
            trace.record("post_scroll", "skipped", "scroll produced no screen change")
            break
        previous_screen = current_screen or previous_screen

    # 5. OCR fallback (last resort)
    res = _resolve(True)
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


def _screen_signature(d: Device) -> tuple[Optional[str], Optional[str]]:
    """Cheap progress signal used to avoid repeating no-op recovery work."""
    try:
        return d.current_activity(), d.dump_hierarchy()
    except Exception:
        return None, None
