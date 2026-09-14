"""Guard: the uiautomator2 API our AndroidDevice adapter relies on still exists.

This can't run the device, but it catches the most likely live-run breakage —
a uiautomator2 upgrade renaming/removing a method the adapter calls — without
any hardware. Skips when uiautomator2 isn't installed.
"""
from __future__ import annotations

import pytest

u2 = pytest.importorskip("uiautomator2")

# methods AndroidDevice calls on the u2 Device handle
DEVICE_METHODS = [
    "app_start", "app_stop", "screenshot", "dump_hierarchy", "app_current",
    "send_keys", "swipe", "press", "window_size", "click",
]
# attributes our _U2Element / resolver use on a selector (UiObject)
UIOBJECT_ATTRS = ["exists", "info", "set_text", "click", "center", "scroll"]


@pytest.mark.parametrize("name", DEVICE_METHODS)
def test_device_handle_has_method(name):
    assert hasattr(u2.Device, name), f"uiautomator2.Device is missing '{name}'"


def test_connect_exists():
    assert hasattr(u2, "connect")


@pytest.mark.parametrize("attr", UIOBJECT_ATTRS)
def test_uiobject_has_attr(attr):
    from uiautomator2._selector import UiObject
    assert hasattr(UiObject, attr), f"uiautomator2 UiObject is missing '{attr}'"
