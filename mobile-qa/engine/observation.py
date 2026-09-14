"""Observation layer — capture one concrete snapshot of the device.

``observe`` is called once before and once after every step. It reaches the
device only through the :class:`~engine.device.Device` interface, so it works
identically against a real device and a FakeDevice.
"""
from __future__ import annotations

import time
from typing import Optional

from .device import Device
from .models import Observation


def observe(d: Device, screenshot_path: Optional[str] = None) -> Observation:
    """Snapshot package, activity, hierarchy, keyboard state and (optionally) a
    screenshot into ``screenshot_path``.

    Each sub-probe is guarded so a single flaky reading never aborts the whole
    observation — a partial snapshot is still useful evidence.
    """
    shot: Optional[str] = None
    if screenshot_path is not None:
        try:
            shot = d.screenshot(screenshot_path)
        except Exception:
            shot = None

    return Observation(
        timestamp=time.time(),
        package=_safe(d.current_package),
        activity=_safe(d.current_activity),
        screenshot_path=shot,
        hierarchy_xml=_safe(d.dump_hierarchy) or "",
        keyboard_visible=bool(_safe(d.keyboard_visible)),
    )


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
