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

    Stable means two consecutive hierarchy dumps ~``interval`` apart match and
    the activity is unchanged, confirmed over two stable pairs so a single
    coincidental match cannot settle a still-animating screen. A failed dump is
    never treated as stable (two read errors must not masquerade as settled).
    With ``require_screen_stable`` it additionally waits for two screenshots to
    be pixel-idle. When ``changed_from`` (the pre-action hierarchy) is given,
    stability is not accepted while the screen still equals that baseline for the
    first half of the timeout, so an async update that has not begun cannot be
    read as settled; after that grace a no-op action still settles. Returns True
    on observed stability, False on timeout. ``sleep`` is injectable for tests.
    """
    start = time.monotonic()
    deadline = start + timeout
    _safe(d.invalidate)  # settle must read the live screen, never a memoized one
    prev_xml = _safe(d.dump_hierarchy)
    prev_act = _safe(d.current_activity)
    stable_streak = 0

    while time.monotonic() < deadline:
        sleep(interval)
        _safe(d.invalidate)
        cur_xml = _safe(d.dump_hierarchy)
        cur_act = _safe(d.current_activity)
        readable = cur_xml is not None and prev_xml is not None
        stable = readable and cur_xml == prev_xml and cur_act == prev_act
        if stable and changed_from is not None and cur_xml == changed_from:
            if (time.monotonic() - start) < timeout / 2:
                stable = False       # action's effect has not landed yet
        if stable and require_screen_stable:
            stable = _frames_idle(d, interval, sleep)
        if stable:
            stable_streak += 1
            if stable_streak >= 2:
                return True
        else:
            stable_streak = 0
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
