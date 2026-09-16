"""settle(): base hierarchy/activity stability plus the optional screen-idle
signal, all driven through FakeDevice so they run with no real device."""
from __future__ import annotations

from engine import stabilize
from tests.fake_device import FakeDevice, FakeScreen

NOSLEEP = lambda _s: None


def test_settle_true_when_screen_is_stable():
    d = FakeDevice([FakeScreen("home", hierarchy_xml="<hierarchy><node/></hierarchy>")])
    assert stabilize.settle(d, sleep=NOSLEEP) is True


def test_settle_times_out_when_hierarchy_never_settles():
    class Churning(FakeDevice):
        def __init__(self):
            super().__init__([FakeScreen("busy")])
            self._n = 0

        def dump_hierarchy(self) -> str:
            self._n += 1
            return f"<hierarchy><node n='{self._n}'/></hierarchy>"

    assert stabilize.settle(Churning(), timeout=0.05, interval=0.001, sleep=NOSLEEP) is False


def test_settle_with_screen_stable_signal_passes_on_static_screen():
    # Identical rendered screenshots -> frames idle -> stable even with the
    # stronger signal on.
    d = FakeDevice([FakeScreen("welcome", ocr_lines=("Welcome",),
                               hierarchy_xml="<hierarchy><node/></hierarchy>")])
    assert stabilize.settle(d, require_screen_stable=True, sleep=NOSLEEP) is True


def test_settle_false_when_dumps_keep_failing():
    # Two consecutive failed dumps must not compare equal (None == None) as stable.
    class Broken(FakeDevice):
        def __init__(self):
            super().__init__([FakeScreen("x", hierarchy_xml="<hierarchy/>")])

        def dump_hierarchy(self):
            raise RuntimeError("adb error")

    assert stabilize.settle(Broken(), timeout=0.05, interval=0.001, sleep=NOSLEEP) is False
