"""Validator: fixed order, per-assertion logic, and the change-detection guard."""
from __future__ import annotations

from engine import validator
from engine.models import Observation, Status
from tests.fake_device import hierarchy, node, render_text


def _obs(xml="", activity="com.example.shop/.Main", shot=None):
    return Observation(timestamp=0.0, activity=activity, hierarchy_xml=xml, screenshot_path=shot)


def test_crash_gate_fires_first():
    after = _obs(hierarchy(node(text="Welcome")))
    out = validator.validate({"type": "text_exists", "value": "Welcome"},
                             after, after, logcat="E FATAL EXCEPTION: boom")
    assert out.status is Status.CRASH
    assert "FATAL EXCEPTION" in out.crash_signature


def test_text_exists_via_hierarchy():
    after = _obs(hierarchy(node(text="Welcome, Sam")))
    out = validator.validate({"type": "text_exists", "value": "Welcome"}, after, after)
    assert out.status is Status.PASS
    assert out.validated_by == "hierarchy"


def test_text_exists_falls_back_to_ocr(tmp_path):
    # hierarchy lacks the text; only the screenshot shows it
    shot = render_text(str(tmp_path / "s.png"), ["PAY NOW"])
    after = _obs(hierarchy(node(text="Cart")), shot=shot)
    out = validator.validate({"type": "text_exists", "value": "PAY NOW"}, after, after)
    assert out.status is Status.PASS
    assert out.validated_by == "ocr"
    assert out.confidence and out.confidence >= 0.6


def test_error_screen_does_not_pass_success_assertion(tmp_path):
    # The false-positive the review flagged: screen changed, but the expected
    # success text is nowhere — must FAIL, never PASS via change detection.
    shot = render_text(str(tmp_path / "s.png"), ["Login failed"])
    after = _obs(hierarchy(node(text="Login failed")), shot=shot)
    out = validator.validate({"type": "text_exists", "value": "Welcome"}, after, after)
    assert out.status is Status.FAIL
    assert out.validated_by is None


def test_activity_is():
    after = _obs(activity="com.example.shop/.HomeActivity")
    ok = validator.validate({"type": "activity_is", "value": ".HomeActivity"}, after, after)
    assert ok.status is Status.PASS and ok.validated_by == "hierarchy"
    bad = validator.validate({"type": "activity_is", "value": ".Login"}, after, after)
    assert bad.status is Status.FAIL


def test_activity_is_not_substring():
    # 'Cart' must not match a different, longer activity that contains it.
    after = _obs(activity="com.example.shop/.ShoppingCartActivity")
    out = validator.validate({"type": "activity_is", "value": "Cart"}, after, after)
    assert out.status is Status.FAIL
    boundary = validator.validate({"type": "activity_is", "value": ".ShoppingCartActivity"},
                                  after, after)
    assert boundary.status is Status.PASS


def test_element_exists():
    after = _obs(hierarchy(node(resource_id="com.example.shop:id/pay")))
    ok = validator.validate({"type": "element_exists", "id": "com.example.shop:id/pay"},
                            after, after)
    assert ok.status is Status.PASS
    bad = validator.validate({"type": "element_exists", "id": "com.example.shop:id/nope"},
                             after, after)
    assert bad.status is Status.FAIL


def test_screen_changed_thresholds():
    before = _obs(hierarchy(node(text="A"), node(text="one two three")))
    after_same = before
    after_diff = _obs(hierarchy(node(text="ZZZ"), node(text="totally different content")))

    out_same = validator.validate({"type": "screen_changed"}, before, after_same)
    assert out_same.status is Status.FAIL and out_same.validated_by == "change"

    out_diff = validator.validate({"type": "screen_changed"}, before, after_diff)
    assert out_diff.status is Status.PASS and out_diff.validated_by == "change"


def test_change_ratio_identical_is_zero():
    obs = _obs(hierarchy(node(text="same")))
    assert validator.change_ratio(obs, obs) == 0.0


def test_text_exists_word_boundary_no_false_pass():
    # opt-in match=word: 'Success' must NOT match inside 'Unsuccessful'.
    after = _obs(hierarchy(node(text="Unsuccessful")))
    out = validator.validate({"type": "text_exists", "value": "Success", "match": "word"},
                             after, after)
    assert out.status is Status.FAIL


def test_text_exists_phrase_as_whole_words():
    after = _obs(hierarchy(node(text="Payment was Successful")))
    out = validator.validate({"type": "text_exists", "value": "Successful"}, after, after)
    assert out.status is Status.PASS


def test_not_visible_word_boundary_no_false_fail():
    # opt-in match=word: 'Cart' as a substring of 'Carthage' must not FAIL not_visible.
    after = _obs(hierarchy(node(text="Carthage ruins")))
    out = validator.validate({"type": "not_visible", "value": "Cart", "match": "word"},
                             after, after)
    assert out.status is Status.PASS


def test_text_exists_contains_mode_is_opt_in():
    after = _obs(hierarchy(node(text="Unsuccessful")))
    out = validator.validate({"type": "text_exists", "value": "success", "match": "contains"},
                             after, after)
    assert out.status is Status.PASS


def test_text_exists_exact_mode():
    after = _obs(hierarchy(node(text="Welcome, Sam")))
    loose = validator.validate({"type": "text_exists", "value": "Welcome", "match": "exact"},
                               after, after)
    assert loose.status is Status.FAIL
    tight = validator.validate({"type": "text_exists", "value": "Welcome, Sam", "match": "exact"},
                               after, after)
    assert tight.status is Status.PASS
