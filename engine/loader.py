"""Loader — parse and validate a YAML test case into a plain dict.

Fails fast with actionable messages so a malformed test case is caught before
the runner ever touches a device.
"""
from __future__ import annotations

from typing import Any

import yaml

ASSERT_TYPES = {
    "text_exists", "ocr_text_exists", "element_exists", "activity_is", "screen_changed",
}
TARGETED_ACTIONS = {"tap", "type", "long_click"}
KNOWN_ACTIONS = TARGETED_ACTIONS | {"launch", "swipe", "back", "wait"}


class TestCaseError(ValueError):
    """Raised when a test case is missing required fields or malformed."""

    __test__ = False  # keep pytest from trying to collect this as a test class


def load_testcase(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        try:
            raw = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise TestCaseError(f"{path}: invalid YAML: {exc}") from exc
    return validate(raw, source=path)


def validate(raw: Any, source: str = "<test case>") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TestCaseError(f"{source}: top level must be a mapping")
    if not raw.get("name"):
        raise TestCaseError(f"{source}: missing 'name'")
    if not raw.get("package"):
        raise TestCaseError(f"{source}: missing 'package'")
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TestCaseError(f"{source}: 'steps' must be a non-empty list")

    for i, step in enumerate(steps):
        _validate_step(step, i, source)

    raw.setdefault("launch_activity", None)
    raw.setdefault("data", {})
    if not isinstance(raw["data"], dict):
        raise TestCaseError(f"{source}: 'data' must be a mapping")
    return raw


def _validate_step(step: Any, i: int, source: str) -> None:
    where = f"{source}: step {i}"
    if not isinstance(step, dict):
        raise TestCaseError(f"{where}: must be a mapping")
    is_action = "action" in step
    is_assert = "assert" in step
    if is_action == is_assert:
        raise TestCaseError(f"{where}: must have exactly one of 'action' or 'assert'")

    if is_action:
        action = step["action"]
        if action not in KNOWN_ACTIONS:
            raise TestCaseError(f"{where}: unknown action '{action}'")
        if action in TARGETED_ACTIONS and not step.get("target"):
            raise TestCaseError(f"{where}: action '{action}' requires a 'target'")
        if action == "type" and "value" not in step:
            raise TestCaseError(f"{where}: action 'type' requires a 'value'")
        if step.get("target") is not None and not isinstance(step["target"], dict):
            raise TestCaseError(f"{where}: 'target' must be a mapping")
    else:
        assertion = step["assert"]
        if not isinstance(assertion, dict):
            raise TestCaseError(f"{where}: 'assert' must be a mapping")
        atype = assertion.get("type")
        if atype not in ASSERT_TYPES:
            raise TestCaseError(f"{where}: unknown assert type '{atype}' "
                                f"(expected one of {sorted(ASSERT_TYPES)})")
        needs_value = atype in {"text_exists", "ocr_text_exists", "activity_is"}
        if needs_value and assertion.get("value") in (None, ""):
            raise TestCaseError(f"{where}: assert '{atype}' requires a 'value'")


def interpolate(value: Any, data: dict[str, Any]) -> Any:
    """Replace ``{{key}}`` placeholders with values from ``data``."""
    if not isinstance(value, str):
        return value
    out = value
    for key, val in data.items():
        out = out.replace("{{" + key + "}}", str(val))
    return out
