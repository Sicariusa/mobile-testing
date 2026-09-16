"""Resolver + recovery: scroll-into-view, OCR fallback, keyboard, BLOCKED."""
from __future__ import annotations

from engine import resolver, recovery
from engine import models
from tests.fake_device import FakeDevice, FakeScreen, hierarchy, node

NOSLEEP = lambda *_a, **_k: None


def test_resolver_selector_priority():
    screen = FakeScreen("home", elements=(
        {"id": "com.example.shop:id/login", "text": "Login", "center": (100, 200), "goto": 0},
    ))
    d = FakeDevice([screen])
    res = resolver.resolve(d, {"id": "com.example.shop:id/login", "text": "Login"})
    assert res.found
    assert res.strategy == models.STRATEGY_RESOURCE_ID  # id wins over text
    assert res.confidence == 1.0


def test_resolver_ocr_fallback_when_selectors_miss():
    # No matching selector element, but the label is painted on screen.
    screen = FakeScreen("promo", ocr_lines=("PAY NOW",), elements=())
    d = FakeDevice([screen])
    res = resolver.resolve(d, {"text": "PAY NOW", "ocr": "PAY NOW"})
    assert res.found
    assert res.strategy == models.STRATEGY_OCR
    assert res.coordinates is not None
    assert res.element is None
    assert 0 < res.confidence <= 1.0


def test_find_with_scroll_reveals_offscreen():
    top = FakeScreen("top", elements=(), scroll_goto=1)
    bottom = FakeScreen("bottom", elements=(
        {"text": "Submit", "center": (100, 400), "goto": 1},
    ))
    d = FakeDevice([top, bottom])
    res = resolver.find_with_scroll(d, {"text": "Submit"}, max_scrolls=3)
    assert res.found
    assert d.scroll_count >= 1


def test_recovery_dismisses_keyboard():
    # The target is genuinely unreachable while the keyboard is up; recovery must
    # dismiss the keyboard and only then resolve it (the branch the old test never
    # exercised — it resolved immediately and asserted nothing).
    class KeyboardGatedDevice(FakeDevice):
        def find(self, kind, value):
            if self.cur.keyboard_visible:      # keyboard covers the control
                return None
            return super().find(kind, value)

    screen = FakeScreen("form", keyboard_visible=True, elements=(
        {"text": "Continue", "center": (100, 500), "goto": 0},
    ))
    d = KeyboardGatedDevice([screen])
    res, trace = recovery.reach(d, {"text": "Continue"}, sleep=NOSLEEP)
    assert res is not None and res.found
    steps = [(a["method"], a["outcome"]) for a in trace.attempts]
    assert ("dismiss_keyboard", "hidden") in steps        # the keyboard branch ran
    assert ("post_keyboard", "resolved") in steps         # and it resolved after
    assert d.cur.keyboard_visible is False                # keyboard actually gone


def test_recovery_scroll_then_resolve():
    top = FakeScreen("top", elements=(), scroll_goto=1)
    bottom = FakeScreen("bottom", elements=(
        {"text": "Buy", "center": (100, 400), "goto": 1},
    ))
    d = FakeDevice([top, bottom])
    res, trace = recovery.reach(d, {"text": "Buy"}, sleep=NOSLEEP)
    assert res is not None and res.found
    assert any(a["method"] == "post_scroll" and a["outcome"] == "resolved"
               for a in trace.attempts)


def test_recovery_stops_redundant_retries_on_unchanged_screen():
    screen = FakeScreen("empty", hierarchy_xml="<hierarchy></hierarchy>")
    d = FakeDevice([screen])
    res, trace = recovery.reach(d, {"text": "Missing"}, sleep=NOSLEEP)
    assert res is None
    assert any(a["outcome"] == "skipped" and "unchanged" in a["detail"]
               for a in trace.attempts)
    assert d.scroll_count == 1


def test_recovery_gives_up_blocked():
    screen = FakeScreen("empty", elements=(), ocr_lines=("nothing useful here",))
    d = FakeDevice([screen])
    res, trace = recovery.reach(d, {"text": "Nonexistent", "ocr": "Nonexistent"},
                                sleep=NOSLEEP)
    assert res is None
    methods = [a["method"] for a in trace.attempts]
    # full escalation was attempted before giving up
    assert "immediate" in methods and "retry" in methods
    assert "scroll" in methods and "ocr" in methods
