"""Executor — perform one ACTION step and return a populated ActionResult.

Implements the action half of the section-6 loop:

    before = observe
    resolve_with_recovery(target)      # selectors -> scroll -> keyboard -> OCR
      -> None            => BLOCKED
    perform(action, resolution, value)
    settle
    after = observe
    status = CRASH if fatal-in-logcat else PASS

Assertions are handled by the validator (invoked from the runner) because a
``screen_changed`` assertion must reason over the *preceding action's*
before/after, not a no-op interval.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from . import models
from .device import Device
from .models import ActionResult, RecoveryTrace, Status, now_ms
from .observation import observe
from .recovery import reach
from .stabilize import settle
from .validator import logcat_fatal

# Actions that require a resolved target
TARGETED_ACTIONS = {"tap", "type", "long_click"}


def execute(d: Device, step: dict[str, Any], *,
            data: Optional[dict[str, Any]] = None,
            package: Optional[str] = None,
            launch_activity: Optional[str] = None,
            before_path: Optional[str] = None,
            after_path: Optional[str] = None,
            sleep=time.sleep,
            settle_fn=settle) -> ActionResult:
    """Execute a single action step. Never raises for expected failures — it
    encodes them in the returned ActionResult's status."""
    data = data or {}
    action = step.get("action")
    target = step.get("target")
    value = _interpolate(step.get("value"), data)
    started = now_ms()

    before = observe(d, before_path)

    resolved_by: Optional[str] = None
    resolved_conf: Optional[float] = None
    recovery = RecoveryTrace()
    detail = ""
    error = ""
    status = Status.PASS

    try:
        if action == "launch":
            if not package:
                raise ValueError("launch requires a package")
            d.launch(package, launch_activity)
            detail = f"launched {package}"
        elif action in TARGETED_ACTIONS:
            if not target:
                raise ValueError(f"action '{action}' requires a target")
            res, recovery = reach(d, target, sleep=sleep)
            if res is None or not res.found:
                after = observe(d, after_path)
                return ActionResult(
                    status=Status.BLOCKED, action=action, target=target, value=value,
                    recovery=recovery, before=before, after=after,
                    duration_ms=now_ms() - started,
                    detail="target unreachable after recovery",
                )
            resolved_by = res.strategy
            resolved_conf = res.confidence
            _perform(d, action, res, value)
        elif action == "swipe":
            _swipe(d, step)
            detail = "swiped"
        elif action == "back":
            d.press_back()
            detail = "pressed back"
        elif action == "wait":
            sleep(float(step.get("seconds", 1.0)))
            detail = "waited"
        else:
            after = observe(d, after_path)
            return ActionResult(
                status=Status.FAIL, action=action or "?", target=target, value=value,
                before=before, after=after, duration_ms=now_ms() - started,
                error=f"unknown action: {action}",
            )
    except Exception as exc:
        after = observe(d, after_path)
        return ActionResult(
            status=Status.FAIL, action=action or "?", target=target, value=value,
            recovery=recovery, before=before, after=after,
            duration_ms=now_ms() - started, error=str(exc),
        )

    settle_fn(d)
    after = observe(d, after_path)

    # crash gate
    fatal = logcat_fatal(_safe_logcat(d))
    if fatal:
        status = Status.CRASH

    return ActionResult(
        status=status, action=action, target=target, value=value,
        resolved_by=resolved_by, resolved_confidence=resolved_conf,
        recovery=recovery, before=before, after=after,
        duration_ms=now_ms() - started, detail=detail, error=error,
        crash_signature=fatal or "",
    )


def _perform(d: Device, action: str, res, value: Optional[str]) -> None:
    """Carry out a resolved action via element handle or OCR coordinates."""
    if action == "tap":
        if res.element is not None:
            res.element.click()
        else:
            d.tap_xy(*res.coordinates)
    elif action == "long_click":
        if res.element is not None:
            res.element.click()  # element long-click optional; click is the MVP
        else:
            d.tap_xy(*res.coordinates)
    elif action == "type":
        if value is None:
            raise ValueError("type requires a value")
        if res.element is not None:
            res.element.set_text(value)
        else:
            d.tap_xy(*res.coordinates)
            d.input_text(value)


def _swipe(d: Device, step: dict[str, Any]) -> None:
    frm = step.get("from")
    to = step.get("to")
    if frm and to:
        d.swipe(int(frm[0]), int(frm[1]), int(to[0]), int(to[1]),
                float(step.get("duration", 0.2)))
    else:
        d.scroll_forward()


def _interpolate(value: Any, data: dict[str, Any]) -> Any:
    """Replace ``{{key}}`` placeholders in a string value with ``data[key]``."""
    if not isinstance(value, str):
        return value
    out = value
    for key, val in data.items():
        out = out.replace("{{" + key + "}}", str(val))
    return out


def _safe_logcat(d: Device) -> str:
    try:
        return d.logcat_since_launch()
    except Exception:
        return ""
