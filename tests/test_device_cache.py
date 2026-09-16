"""AndroidDevice hierarchy memo: back-to-back reads reuse one live dump; any
mutating action invalidates it. This is the Stage-1 speed win."""
from __future__ import annotations

from engine import config, models
from engine.device import AndroidDevice


class _StubSelector:
    """A u2 selector handle whose click()/set_text() mutate the screen — used to
    drive a real _U2Element through the owner-invalidation wiring."""
    def __init__(self, u2):
        self._u2 = u2
        self.exists = True

    def click(self):
        self._u2._xml = "<hierarchy><node text='clicked'/></hierarchy>"

    def set_text(self, value):
        self._u2._xml = "<hierarchy><node text='typed'/></hierarchy>"


class StubU2:
    """Minimal uiautomator2 stand-in that counts real dumps."""
    def __init__(self):
        self.dumps = 0
        self._xml = "<hierarchy><node text='A'/></hierarchy>"

    def __call__(self, **kwargs):
        return _StubSelector(self)

    def dump_hierarchy(self):
        self.dumps += 1
        return self._xml

    def app_current(self):
        return {"activity": ".Main", "package": "app"}

    def click(self, x, y):
        self._xml = "<hierarchy><node text='B'/></hierarchy>"

    def send_keys(self, value):
        pass

    def press(self, key):
        pass

    def swipe(self, *a, **k):
        pass


def _dev():
    return AndroidDevice(StubU2(), serial="stub")


def test_back_to_back_reads_use_one_dump():
    config.HIERARCHY_CACHE = True
    d = _dev()
    a = d.dump_hierarchy()
    b = d.dump_hierarchy()
    c = d.dump_hierarchy()
    assert a == b == c
    assert d._d.dumps == 1  # only the first read hit the device


def test_action_invalidates_the_memo():
    config.HIERARCHY_CACHE = True
    d = _dev()
    first = d.dump_hierarchy()
    d.tap_xy(10, 10)                 # mutating → invalidate
    second = d.dump_hierarchy()
    assert first != second           # sees the post-action screen
    assert d._d.dumps == 2


def test_element_click_invalidates_via_owner():
    config.HIERARCHY_CACHE = True
    d = _dev()
    d.dump_hierarchy()               # prime the memo
    before = d._d.dumps
    el = d.find(models.STRATEGY_TEXT_EXACT, "A")   # a REAL _U2Element owned by d
    assert el is not None
    el.click()                       # _sel.click() -> _touched() -> owner.invalidate()
    d.dump_hierarchy()
    assert d._d.dumps == before + 1  # memo was dropped, so a live re-dump happened
    assert "clicked" in d.dump_hierarchy()   # and it reflects the post-click screen


def test_element_set_text_invalidates_via_owner():
    config.HIERARCHY_CACHE = True
    d = _dev()
    d.dump_hierarchy()
    before = d._d.dumps
    el = d.find(models.STRATEGY_RESOURCE_ID, "app:id/field")
    el.set_text("hello")             # must invalidate the memo like click()
    assert d._d.dumps == before      # set_text itself does not dump
    assert "typed" in d.dump_hierarchy()   # next read is live, not the stale memo


def test_cache_off_always_dumps():
    config.HIERARCHY_CACHE = False
    try:
        d = _dev()
        d.dump_hierarchy()
        d.dump_hierarchy()
        assert d._d.dumps == 2
    finally:
        config.HIERARCHY_CACHE = True
