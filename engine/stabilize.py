"""Stabilisation — wait for the screen to settle before observing/acting.

MVP definition of "settled": two hierarchy dumps taken ~SETTLE_POLL_INTERVAL_S
apart are identical AND the activity did not change between them, or we hit
SETTLE_TIMEOUT_S. Written so richer signals (animation frames, network idle)
can be added later without changing any caller.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

from .config import (SETTLE_POLL_INTERVAL_S, SETTLE_REQUIRE_SCREEN_STABLE,
                     SETTLE_SCREEN_EPSILON, SETTLE_TIMEOUT_S)
from .device import Device


def settle(d: Device, timeout: float = SETTLE_TIMEOUT_S,
           interval: float = SETTLE_POLL_INTERVAL_S,
           require_screen_stable: bool = SETTLE_REQUIRE_SCREEN_STABLE,
           changed_from: str | None = None,
           sleep=time.sleep) -> bool:
    """Block until the screen is stable or ``timeout`` elapses.

    Stable means two hierarchy dumps ~``interval`` apart match and the activity
    is unchanged; a failed dump is never treated as stable (two read errors must
    not masquerade as settled). With ``require_screen_stable`` it additionally
    waits for two screenshots to be pixel-idle. (``changed_from`` is accepted for
    call-site compatibility but not used — waiting on it stalled live runs.)
    Returns True on observed stability, False on timeout. ``sleep`` is injectable.
    """
    deadline = time.monotonic() + timeout
    _safe(d.invalidate)  # settle must read the live screen, never a memoized one
    prev_xml = _safe(d.dump_hierarchy)
    prev_act = _safe(d.current_activity)

    while time.monotonic() < deadline:
        sleep(interval)
        _safe(d.invalidate)
        cur_xml = _safe(d.dump_hierarchy)
        cur_act = _safe(d.current_activity)
        stable = cur_xml is not None and cur_xml == prev_xml and cur_act == prev_act
        if stable and require_screen_stable:
            stable = _frames_idle(d, interval, sleep)
        if stable:
            return True
        prev_xml, prev_act = cur_xml, cur_act
    return False


def _frames_idle(d: Device, interval: float, sleep) -> bool:
    """True when two screenshots ~interval apart differ by <= the epsilon. A
    measurement failure returns True so this optional signal never blocks."""
    from . import observation, validator  # lazy: keeps the base settle path light

    tmp = tempfile.mkdtemp(prefix="settle_")
    try:
        a = observation.observe(d, os.path.join(tmp, "a.png"))
        sleep(interval)
        b = observation.observe(d, os.path.join(tmp, "b.png"))
        if not a.screenshot_path or not b.screenshot_path:
            return True
        return validator.change_ratio(a, b) <= SETTLE_SCREEN_EPSILON
    except Exception:
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
