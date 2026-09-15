"""Runner — drive a whole test case end to end.

Responsibilities:
  * load + validate the YAML test case
  * (optionally) install the APK
  * iterate steps: ACTION steps go through the executor; ASSERT steps are
    validated against the right before/after observations
  * stop on the first CRASH or BLOCKED and mark the remaining steps SKIPPED
  * persist evidence, timeline.json, logcat.txt and the HTML report
  * return an overall result

The device is injected, so the runner is exercised end to end in tests against
a FakeDevice with no Android present.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional, Union

from . import executor as executor_mod
from . import report as report_mod
from . import validator as validator_mod
from .device import Device
from .evidence import Evidence
from .loader import load_testcase, validate as validate_testcase
from .models import ActionResult, FailureReason, Status, now_ms
from .observation import observe
from .selector_cache import SelectorCache
from .screen_library import ScreenLibrary

# statuses that abort the rest of the run
FATAL_STATUSES = {Status.CRASH, Status.BLOCKED}


def run(testcase: Union[str, dict[str, Any]], device: Device, *,
        apk_path: Optional[str] = None,
        base_dir: str = "reports",
        run_id: Optional[str] = None,
        sleep=time.sleep,
        settle_fn=None) -> dict[str, Any]:
    """Execute ``testcase`` (a YAML path or an already-parsed dict) on ``device``.

    Returns a result dict: ``{overall, run_id, report_path, timeline_path,
    counts, results}``.
    """
    tc = load_testcase(testcase) if isinstance(testcase, str) else validate_testcase(testcase)
    package = tc["package"]
    launch_activity = tc.get("launch_activity")
    data = tc.get("data", {})
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")

    ev = Evidence(run_id, base_dir=base_dir)
    cache = SelectorCache(package)
    library = ScreenLibrary(package)

    if apk_path:
        device.install(apk_path)

    results: list[ActionResult] = []
    aborted = False
    # track the most recent ACTION's before/after for screen_changed assertions
    last_before = observe(device)
    last_after = last_before

    settle_kwargs = {} if settle_fn is None else {"settle_fn": settle_fn}

    for i, step in enumerate(tc["steps"]):
        before_path, after_path = ev.screenshot_paths(i)

        if aborted:
            res = ActionResult(status=Status.SKIPPED, action=_step_name(step),
                               target=step.get("target"),
                               detail="skipped after fatal step")
            results.append(res)
            ev.save_step(i, res)
            continue

        if "assert" in step:
            res = _run_assert(device, step["assert"], last_before, last_after,
                              after_path, _safe_logcat(device))
        else:
            res = executor_mod.execute(
                device, step, data=data, package=package,
                launch_activity=launch_activity,
                before_path=before_path, after_path=after_path,
                sleep=sleep, cache=cache, library=library, **settle_kwargs,
            )
            if res.before is not None:
                last_before = res.before
            if res.after is not None:
                last_after = res.after

        results.append(res)
        ev.save_step(i, res)
        if res.status in FATAL_STATUSES:
            aborted = True

    ev.write_logcat(_safe_logcat(device))
    cache.save()
    ev.write_bindings(cache.bindings())
    overall = _overall(results)
    counts = _counts(results)
    meta = {
        "name": tc["name"], "package": package, "run_id": run_id,
        "overall": overall.value, "counts": counts,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    timeline_path = ev.write_timeline(meta)
    report_path = report_mod.render({"meta": meta, "steps": ev.timeline},
                                    f"{ev.run_dir}/report.html")

    return {
        "overall": overall.value,
        "run_id": run_id,
        "report_path": report_path,
        "timeline_path": timeline_path,
        "counts": counts,
        "results": results,
    }


def _run_assert(device: Device, assertion: dict[str, Any],
                last_before, last_after, after_path: str, logcat: str) -> ActionResult:
    """Validate one assertion. ``screen_changed`` reasons over the preceding
    action's before/after; every other assertion over the current screen."""
    started = now_ms()
    current = observe(device, after_path)
    if assertion.get("type") in ("screen_changed", "activity_changed"):
        before, after = last_before, last_after
    else:
        before, after = current, current

    outcome = validator_mod.validate(assertion, before, after, logcat)
    ocr_matches = _collect_ocr(after, assertion, outcome.validated_by)

    # On a non-PASS, classify and attach structured evidence so the failure is a
    # readable report, not a bare FAIL. The screen summary is the *post-condition*
    # observation the assertion evaluated (the failure state), not `before`.
    failure_reason = None
    screen_summary = None
    if outcome.status == Status.CRASH:
        failure_reason = FailureReason.APP_CRASHED
    elif outcome.status != Status.PASS:
        failure_reason = FailureReason.ASSERTION_FAILED
    if outcome.status != Status.PASS:
        screen_summary = _screen_summary(after)

    return ActionResult(
        status=outcome.status,
        action=f"assert:{assertion.get('type')}",
        target=None,
        value=assertion.get("value"),
        validated_by=outcome.validated_by,
        validation_confidence=outcome.confidence,
        before=before, after=after,
        duration_ms=now_ms() - started,
        ocr_matches=ocr_matches,
        detail=outcome.detail,
        crash_signature=outcome.crash_signature,
        failure_reason=failure_reason,
        screen_summary=screen_summary,
        expected=outcome.expected,
        actual=outcome.actual,
        observed_texts=list(outcome.observed_texts or []),
    )


def _screen_summary(obs) -> Optional[dict[str, Any]]:
    """{activity, element_count, window} for the observation an assertion checked
    — the same shape executor._diagnose builds for a blocked action."""
    if obs is None:
        return None
    try:
        return {"activity": obs.activity, "element_count": len(obs.elements()),
                "window": obs.window()}
    except Exception:
        return {"activity": getattr(obs, "activity", None)}


def _collect_ocr(after, assertion, validated_by) -> list[dict[str, Any]]:
    """Attach OCR match evidence when OCR was involved."""
    if not after or not after.screenshot_path:
        return []
    if assertion.get("type") not in ("text_exists", "ocr_text_exists"):
        return []
    try:
        from . import ocr as ocr_mod
        return ocr_mod.ocr_find(after.screenshot_path, assertion.get("value") or "")[:5]
    except Exception:
        return []


def _step_name(step: dict[str, Any]) -> str:
    if "assert" in step:
        return f"assert:{step['assert'].get('type')}"
    return step.get("action", "?")


def _overall(results: list[ActionResult]) -> Status:
    order = [Status.CRASH, Status.BLOCKED, Status.FAIL]
    for status in order:
        if any(r.status == status for r in results):
            return status
    return Status.PASS


def _counts(results: list[ActionResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        key = r.status.value if isinstance(r.status, Status) else str(r.status)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _safe_logcat(device: Device) -> str:
    try:
        return device.logcat_since_launch()
    except Exception:
        return ""
