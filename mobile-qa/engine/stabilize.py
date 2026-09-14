"""Stabilisation — wait for the screen to settle before observing/acting.

MVP definition of "settled": two hierarchy dumps taken ~SETTLE_POLL_INTERVAL_S
apart are identical AND the activity did not change between them, or we hit
SETTLE_TIMEOUT_S. Written so richer signals (animation frames, network idle)
can be added later without changing any caller.
"""
from __future__ import annotations

import time

from .config import SETTLE_POLL_INTERVAL_S, SETTLE_TIMEOUT_S
from .device import Device


def settle(d: Device, timeout: float = SETTLE_TIMEOUT_S,
           interval: float = SETTLE_POLL_INTERVAL_S,
           sleep=time.sleep) -> bool:
    """Block until the screen is stable or ``timeout`` elapses.

    Returns True if it observed stability, False if it timed out. ``sleep`` is
    injectable so tests run instantly.
    """
    deadline = time.monotonic() + timeout
    prev_xml = _safe(d.dump_hierarchy)
    prev_act = _safe(d.current_activity)

    while time.monotonic() < deadline:
        sleep(interval)
        cur_xml = _safe(d.dump_hierarchy)
        cur_act = _safe(d.current_activity)
        if cur_xml == prev_xml and cur_act == prev_act:
            return True
        prev_xml, prev_act = cur_xml, cur_act
    return False


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
