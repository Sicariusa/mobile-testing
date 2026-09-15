"""Failure classification & structured evidence — a failed assertion is reported
as a defect with expected/actual/observed + a post-condition screenshot, and is
distinct from a BLOCKED (couldn't-reach-target) action. No device: FakeDevice.
"""
from __future__ import annotations

from engine import executor as executor_mod
from engine import report as report_mod
from engine import runner as runner_mod
from engine.models import FailureReason, Status
from engine.observation import observe

from tests.fake_device import FakeDevice, FakeScreen, hierarchy, node

# A product screen with ADD TO CART present but REMOVE absent — asserting REMOVE
# (the correct post-add behaviour) must FAIL and be flagged.
PRODUCT_XML = hierarchy(
    node(text="Backpack", clickable="false", bounds="[0,100][1080,300]"),
    node(text="$29.99", clickable="false", bounds="[0,1200][1080,1340]"),
    node(text="ADD TO CART", content_desc="test-ADD TO CART", clickable="true",
         bounds="[0,1500][1080,1660]"),
)


def _product_device():
    return FakeDevice([FakeScreen(
        name="product", activity="com.example.shop/.MainActivity",
        hierarchy_xml=PRODUCT_XML, ocr_lines=("Backpack", "$29.99", "ADD TO CART"),
    )])


def test_failed_assertion_is_classified_and_evidenced(tmp_path):
    dev = _product_device()
    obs = observe(dev, str(tmp_path / "b.png"))
    res = runner_mod._run_assert(
        dev, {"type": "text_exists", "value": "REMOVE"},
        obs, obs, str(tmp_path / "after.png"), logcat="")

    assert res.status == Status.FAIL
    assert res.failure_reason == FailureReason.ASSERTION_FAILED
    assert res.expected == "REMOVE"
    assert res.actual is None
    # the actual on-screen texts are attached as evidence
    assert any("ADD TO CART" in t for t in res.observed_texts)
    assert res.screen_summary and res.screen_summary.get("element_count", 0) >= 1


def test_failed_assertion_screenshot_is_the_post_condition(tmp_path):
    dev = _product_device()
    before = observe(dev, str(tmp_path / "before.png"))
    after_path = str(tmp_path / "after.png")
    res = runner_mod._run_assert(
        dev, {"type": "text_exists", "value": "REMOVE"},
        before, before, after_path, logcat="")
    # evidence for the failure is the post-condition screenshot, not `before`
    assert res.after is not None
    assert res.after.screenshot_path == after_path
    assert res.after.screenshot_path != before.screenshot_path


def test_report_renders_expected_observed_and_defect_tag(tmp_path):
    timeline = {
        "meta": {"name": "bug run", "overall": "FAIL", "run_id": "r1",
                 "package": "com.example.shop"},
        "steps": [{
            "index": 3, "status": "FAIL", "action": "assert:text_exists",
            "failure_reason": FailureReason.ASSERTION_FAILED,
            "expected": "REMOVE", "actual": None,
            "observed_texts": ["ADD TO CART", "$29.99", "Backpack"],
            "screen_summary": {"activity": ".MainActivity", "element_count": 3,
                               "window": {"dialog": False, "keyboard": False}},
        }],
    }
    out = report_mod.render(timeline, str(tmp_path / "report.html"))
    html = open(out, encoding="utf-8").read()
    assert "Expected" in html and "REMOVE" in html
    assert "Observed on screen" in html and "ADD TO CART" in html
    assert "Likely defect" in html


def test_blocked_action_and_failed_assertion_are_distinct(tmp_path):
    # Case A — target absent → the ACTION is BLOCKED (couldn't reach target).
    dev = _product_device()
    blocked = executor_mod.execute(
        dev, {"action": "tap", "target": "Totally Nonexistent Button"},
        package="com.example.shop", before_path=str(tmp_path / "ba.png"),
        after_path=str(tmp_path / "bb.png"),
        sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    assert blocked.status == Status.BLOCKED
    assert blocked.failure_reason != FailureReason.ASSERTION_FAILED

    # Case B — target present, but the expected outcome is not observed → FAIL.
    dev2 = _product_device()
    obs = observe(dev2, str(tmp_path / "c.png"))
    failed = runner_mod._run_assert(
        dev2, {"type": "text_exists", "value": "REMOVE"},
        obs, obs, str(tmp_path / "after.png"), logcat="")
    assert failed.status == Status.FAIL
    assert failed.failure_reason == FailureReason.ASSERTION_FAILED

    # the two read differently — the core distinction
    assert (blocked.status, blocked.failure_reason) != (failed.status, failed.failure_reason)
