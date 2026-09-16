"""long_click must perform a real long press, not a short tap (audit C2)."""
from __future__ import annotations

from engine import executor


class _SpyElement:
    def __init__(self):
        self.clicks = 0
        self.long_clicks = 0

    def click(self):
        self.clicks += 1

    def long_click(self):
        self.long_clicks += 1


class _SpyDevice:
    def __init__(self):
        self.taps = []
        self.long_taps = []

    def tap_xy(self, x, y):
        self.taps.append((x, y))

    def long_click_xy(self, x, y):
        self.long_taps.append((x, y))


class _Res:
    def __init__(self, element=None, coordinates=None):
        self.element = element
        self.coordinates = coordinates


def test_long_click_uses_element_long_press():
    el = _SpyElement()
    executor._perform(_SpyDevice(), "long_click", _Res(element=el), None)
    assert el.long_clicks == 1 and el.clicks == 0


def test_long_click_uses_coordinate_long_press():
    dev = _SpyDevice()
    executor._perform(dev, "long_click", _Res(coordinates=(120, 340)), None)
    assert dev.long_taps == [(120, 340)] and dev.taps == []


def test_plain_tap_still_short_taps():
    el = _SpyElement()
    executor._perform(_SpyDevice(), "tap", _Res(element=el), None)
    assert el.clicks == 1 and el.long_clicks == 0
