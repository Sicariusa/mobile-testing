"""Phase 4 — not_visible + activity_changed assertions."""
from __future__ import annotations

from engine import validator
from engine.models import Observation, Status
from tests.fake_device import render_text


def _o(xml, activity="A"):
    return Observation(timestamp=0.0, activity=activity, hierarchy_xml=xml)


def test_not_visible_pass_when_absent_fail_when_present():
    absent = _o("<hierarchy><node text='Done'/></hierarchy>")
    present = _o("<hierarchy><node text='Loading'/></hierarchy>")
    a = validator.validate({"type": "not_visible", "value": "Loading"}, absent, absent)
    p = validator.validate({"type": "not_visible", "value": "Loading"}, present, present)
    assert a.status is Status.PASS
    assert p.status is Status.FAIL


def test_not_visible_fails_when_text_only_in_pixels(tmp_path):
    # gone from the tree but still painted on screen -> must FAIL (OCR branch)
    shot = render_text(str(tmp_path / "s.png"), ["Loading"])
    obs = Observation(timestamp=0.0, activity="A",
                      hierarchy_xml="<hierarchy><node text='Home'/></hierarchy>",
                      screenshot_path=shot)
    out = validator.validate({"type": "not_visible", "value": "Loading"}, obs, obs)
    assert out.status is Status.FAIL


def test_not_visible_does_not_silently_pass_when_ocr_cannot_run(tmp_path):
    # a screenshot exists but OCR errors on it -> we cannot confirm absence, so
    # the negative assertion must not silently PASS
    obs = Observation(timestamp=0.0, activity="A",
                      hierarchy_xml="<hierarchy><node text='Home'/></hierarchy>",
                      screenshot_path=str(tmp_path / "missing.png"))
    out = validator.validate({"type": "not_visible", "value": "Loading"}, obs, obs)
    assert out.status is not Status.PASS


def test_activity_changed():
    a, b = _o("<hierarchy/>", "LoginActivity"), _o("<hierarchy/>", "HomeActivity")
    assert validator.validate({"type": "activity_changed"}, a, b).status is Status.PASS
    assert validator.validate({"type": "activity_changed"}, a, a).status is Status.FAIL
