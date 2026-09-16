"""app_current/keyboard memoization (audit P3): one round-trip per screen state."""
from __future__ import annotations

from engine.device import AndroidDevice


class _FakeU2:
    def __init__(self):
        self.app_current_calls = 0

    def app_current(self):
        self.app_current_calls += 1
        return {"package": "com.example.shop", "activity": ".Main"}


def test_app_current_is_memoized_across_package_and_activity():
    u = _FakeU2()
    d = AndroidDevice(u)
    # a cold observation reads package then activity — one app_current, not two
    assert d.current_package() == "com.example.shop"
    assert d.current_activity() == ".Main"
    assert u.app_current_calls == 1
    # a mutating action invalidates -> next read is live again
    d.invalidate()
    d.current_activity()
    assert u.app_current_calls == 2
