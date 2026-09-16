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

from . import inspect as inspect_mod
from . import models
from . import resolver as resolver_mod
from .device import Device
from .models import ActionResult, FailureReason, RecoveryTrace, Status, now_ms
from .observation import observe
from .recovery import reach
from .stabilize import settle
from .validator import logcat_fatal

# Labels a bare `submit` will try, in order, when no target is given.
SUBMIT_LABELS = ("Submit", "Continue", "Next", "Sign in", "Log in", "Login",
                 "Done", "Confirm")


def _norm_target(target):
    """A string target is an intent label → {'label': ...}; a mapping passes through."""
    if isinstance(target, str):
        return {"label": target}
    return target


def _hide_keyboard(d, sleep, visible: Optional[bool] = None) -> None:
    """Dismiss an open keyboard before a tap/submit: it obscures buttons and its
    IME action key (Next/Done/Go) would otherwise win the submit ranking.

    ``visible`` lets the caller pass the keyboard state it already observed this
    step so we don't pay a second ``dumpsys input_method`` round-trip.
    """
    try:
        if visible is None:
            visible = d.keyboard_visible()
        if visible:
            d.press_back()
            sleep(0.3)
    except Exception:
        pass


def _resolve_submit(d, target, cache, sleep, library=None):
    """Find the submit control: an explicit target, else the first matching
    common submit label on the current screen."""
    if target:
        return reach(d, target, sleep=sleep, role="tappable", cache=cache, library=library)
    for label in SUBMIT_LABELS:
        r = resolver_mod.resolve(d, {"label": label}, allow_ocr=False,
                                 role="tappable", cache=cache)
        if r.found:
            return r, RecoveryTrace()
    return reach(d, {"label": SUBMIT_LABELS[0]}, sleep=sleep, role="tappable",
                 cache=cache, library=library)


def _diagnose(target: Optional[dict[str, Any]], action: str, after) -> tuple:
    """Turn a failed resolution into (reason, ranked suggestions, screen summary)
    so a broken step shows the real on-screen selectors, not a bare BLOCKED."""
    reason = FailureReason.TARGET_NOT_FOUND
    suggestions: list[dict[str, Any]] = []
    summary = None
    try:
        els = after.elements() if after else []
        if after and after.window().get("dialog"):
            reason = FailureReason.UNEXPECTED_SCREEN
        query = ""
        if target:
            query = (target.get("text") or target.get("label")
                     or target.get("desc") or "")
            if not query and target.get("id"):
                query = target["id"].rsplit("/", 1)[-1]
        role = "field" if action == "type" else "tappable"
        if query:
            suggestions = [c.as_dict()
                           for c in inspect_mod.rank_candidates(query, els, role=role)]
        summary = {
            "activity": after.activity if after else None,
            "element_count": len(els),
            "window": after.window() if after else {},
        }
    except Exception:
        pass
    return reason, suggestions, summary

# Actions that require a resolved target
TARGETED_ACTIONS = {"tap", "type", "long_click", "enter_text"}


def execute(d: Device, step: dict[str, Any], *,
            data: Optional[dict[str, Any]] = None,
            package: Optional[str] = None,
            launch_activity: Optional[str] = None,
            before_path: Optional[str] = None,
            after_path: Optional[str] = None,
            sleep=time.sleep,
            settle_fn=settle,
            cache=None,
            library=None) -> ActionResult:
    """Execute a single action step. Never raises for expected failures — it
    encodes them in the returned ActionResult's status."""
    data = data or {}
    action = step.get("action")
    target = _norm_target(step.get("target"))
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
        elif action in TARGETED_ACTIONS or action == "submit":
            if action in ("tap", "submit", "long_click"):
                _hide_keyboard(d, sleep, before.keyboard_visible)
            if action == "submit":
                res, recovery = _resolve_submit(d, target, cache, sleep, library)
            else:
                if not target:
                    raise ValueError(f"action '{action}' requires a target")
                role = "field" if action in ("type", "enter_text") else "tappable"
                res, recovery = reach(d, target, sleep=sleep, role=role,
                                      cache=cache, library=library)
            if res is None or not res.found:
                after = observe(d, after_path)
                reason, suggestions, summary = _diagnose(
                    target or {"label": "submit"}, action, after)
                return ActionResult(
                    status=Status.BLOCKED, action=action, target=target, value=value,
                    recovery=recovery, before=before, after=after,
                    duration_ms=now_ms() - started,
                    detail="target unreachable after recovery",
                    failure_reason=reason, suggestions=suggestions,
                    screen_summary=summary,
                )
            resolved_by = res.strategy
            resolved_conf = res.confidence
            perform_action = "type" if action == "enter_text" else (
                "tap" if action == "submit" else action)
            _perform(d, perform_action, res, value)
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
            failure_reason=FailureReason.DEVICE_ERROR,
        )

    settled = settle_fn(d, changed_from=before.hierarchy_xml)
    if not settled:
        detail = "screen settle timeout"
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
        failure_reason=FailureReason.APP_CRASHED if fatal else None,
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
            res.element.long_click()
        else:
            d.long_click_xy(*res.coordinates)
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
