"""Phase 4 — not_visible + activity_changed assertions."""
from __future__ import annotations

from engine import validator
from engine.models import Observation, Status


def _o(xml, activity="A"):
    return Observation(timestamp=0.0, activity=activity, hierarchy_xml=xml)


def test_not_visible_pass_when_absent_fail_when_present():
    absent = _o("<hierarchy><node text='Done'/></hierarchy>")
    present = _o("<hierarchy><node text='Loading'/></hierarchy>")
    a = validator.validate({"type": "not_visible", "value": "Loading"}, absent, absent)
    p = validator.validate({"type": "not_visible", "value": "Loading"}, present, present)
    assert a.status is Status.PASS
    assert p.status is Status.FAIL


def test_activity_changed():
    a, b = _o("<hierarchy/>", "LoginActivity"), _o("<hierarchy/>", "HomeActivity")
    assert validator.validate({"type": "activity_changed"}, a, b).status is Status.PASS
    assert validator.validate({"type": "activity_changed"}, a, a).status is Status.FAIL
