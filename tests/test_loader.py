"""Loader: schema validation and {{data}} interpolation."""
from __future__ import annotations

import pytest

from engine import loader
from engine.loader import TestCaseError


VALID = {
    "name": "t", "package": "com.example.shop",
    "data": {"email": "a@b.c"},
    "steps": [
        {"action": "launch"},
        {"action": "type", "target": {"id": "x"}, "value": "{{email}}"},
        {"assert": {"type": "text_exists", "value": "Welcome"}},
    ],
}


def test_valid_testcase_passes():
    tc = loader.validate(dict(VALID))
    assert tc["launch_activity"] is None  # defaulted
    assert tc["name"] == "t"


def test_interpolation():
    assert loader.interpolate("{{email}}", {"email": "a@b.c"}) == "a@b.c"
    assert loader.interpolate("no placeholder", {"x": 1}) == "no placeholder"
    assert loader.interpolate(None, {"x": 1}) is None


def test_missing_package_rejected():
    bad = dict(VALID); bad.pop("package")
    with pytest.raises(TestCaseError):
        loader.validate(bad)


def test_step_needs_exactly_one_of_action_or_assert():
    bad = {"name": "t", "package": "p",
           "steps": [{"action": "tap", "assert": {"type": "screen_changed"}}]}
    with pytest.raises(TestCaseError):
        loader.validate(bad)


def test_targeted_action_requires_target():
    bad = {"name": "t", "package": "p", "steps": [{"action": "tap"}]}
    with pytest.raises(TestCaseError):
        loader.validate(bad)


def test_unknown_assert_type_rejected():
    bad = {"name": "t", "package": "p",
           "steps": [{"assert": {"type": "wishful_thinking"}}]}
    with pytest.raises(TestCaseError):
        loader.validate(bad)


def test_loads_sample_login_yaml():
    tc = loader.load_testcase("testcases/login.yaml")
    assert tc["package"] == "com.example.shop"
    assert tc["steps"][0]["action"] == "launch"
