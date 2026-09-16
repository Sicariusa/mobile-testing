"""End-to-end runner tests driven entirely through FakeDevice.

Each scenario asserts the reasoning metadata — exact
``(status, resolved_by, validated_by)`` tuples — not just the overall result,
and the happy path writes a real, openable HTML report.
"""
from __future__ import annotations

import os

from engine import runner
from engine.models import Status
from tests.fake_device import FakeDevice, FakeScreen, hierarchy, node

NOSLEEP = lambda *_a, **_k: None
NOSETTLE = lambda *_a, **_k: True

EMAIL_ID = "com.example.shop:id/email"
PASS_ID = "com.example.shop:id/password"


def _login_testcase():
    return {
        "name": "Login", "package": "com.example.shop",
        "data": {"email": "test@example.com", "password": "Password123"},
        "steps": [
            {"action": "launch"},
            {"action": "tap", "target": {"text": "Login"}},
            {"action": "type", "target": {"id": EMAIL_ID}, "value": "{{email}}"},
            {"action": "type", "target": {"id": PASS_ID}, "value": "{{password}}"},
            {"action": "tap", "target": {"text": "Login"}},
            {"assert": {"type": "text_exists", "value": "Welcome"}},
            {"assert": {"type": "ocr_text_exists", "value": "PAY NOW"}},
            {"assert": {"type": "screen_changed"}},
        ],
    }


def _login_screens():
    landing = FakeScreen(
        "landing", hierarchy_xml=hierarchy(node(text="Login")),
        ocr_lines=("Login",),
        elements=({"text": "Login", "center": (100, 120), "goto": 1},),
    )
    form = FakeScreen(
        "form",
        hierarchy_xml=hierarchy(
            node(resource_id=EMAIL_ID, text=""),
            node(resource_id=PASS_ID, text=""),
            node(text="Login"),
        ),
        ocr_lines=("Login",),
        elements=(
            {"id": EMAIL_ID, "center": (100, 250), "goto": 1},
            {"id": PASS_ID, "center": (100, 350), "goto": 1},
            {"text": "Login", "center": (100, 500), "goto": 2},
        ),
    )
    success = FakeScreen(
        "success", activity="com.example.shop/.HomeActivity",
        hierarchy_xml=hierarchy(node(text="Welcome, Sam")),
        ocr_lines=("Welcome", "PAY NOW"),
    )
    return [landing, form, success]


def _run(tc, screens, tmp_path, **kw):
    d = FakeDevice(screens, logcat=kw.pop("logcat", ""))
    return d, runner.run(tc, d, base_dir=str(tmp_path), run_id="t",
                         sleep=NOSLEEP, settle_fn=NOSETTLE, **kw)


def test_happy_path_tuples_and_report(tmp_path):
    d, result = _run(_login_testcase(), _login_screens(), tmp_path)
    assert result["overall"] == "PASS"

    got = [(r.status, r.action, r.resolved_by, r.validated_by) for r in result["results"]]
    assert got == [
        (Status.PASS, "launch", None, None),
        (Status.PASS, "tap", "text_exact", None),
        (Status.PASS, "type", "resource_id", None),
        (Status.PASS, "type", "resource_id", None),
        (Status.PASS, "tap", "text_exact", None),
        (Status.PASS, "assert:text_exists", None, "hierarchy"),
        (Status.PASS, "assert:ocr_text_exists", None, "ocr"),
        (Status.PASS, "assert:screen_changed", None, "change"),
    ]
    # the typed values were interpolated from data
    assert "test@example.com" in d.typed and "Password123" in d.typed

    # a real report + timeline were written
    assert os.path.exists(result["report_path"])
    assert os.path.exists(result["timeline_path"])
    html = open(result["report_path"], encoding="utf-8").read()
    assert "Login" in html and "PASS" in html


def test_numeric_assertion_value_does_not_crash_the_run(tmp_path):
    # A loader-valid numeric value (e.g. an order total) must yield a clean
    # verdict + a written report, never a traceback that discards the run.
    tc = {
        "name": "Numeric", "package": "com.example.shop",
        "steps": [
            {"action": "launch"},
            {"assert": {"type": "text_exists", "value": 100}},
        ],
    }
    screens = [FakeScreen("home", hierarchy_xml=hierarchy(node(text="Total: 42")))]
    d, result = _run(tc, screens, tmp_path)
    assert os.path.exists(result["report_path"])
    assert os.path.exists(result["timeline_path"])
    statuses = [r.status for r in result["results"]]
    assert Status.FAIL in statuses  # graded, not crashed


def test_text_exists_satisfied_only_by_ocr(tmp_path):
    # success screen whose hierarchy does NOT contain the word, only the pixels
    screens = _login_screens()
    screens[2] = FakeScreen(
        "success", activity="com.example.shop/.HomeActivity",
        hierarchy_xml=hierarchy(node(text="Home")),   # no "Welcome" in tree
        ocr_lines=("Welcome", "PAY NOW"),
    )
    tc = _login_testcase()
    tc["steps"] = tc["steps"][:6]  # up to the text_exists assert
    _d, result = _run(tc, screens, tmp_path)
    welcome = result["results"][-1]
    assert welcome.status is Status.PASS
    assert welcome.validated_by == "ocr"   # hierarchy missed it, OCR caught it


def test_ocr_resolved_tap(tmp_path):
    # A button reachable only via OCR (no selector), tapped by coordinates.
    promo = FakeScreen("promo", hierarchy_xml=hierarchy(node(text="Cart")),
                       ocr_lines=("CHECKOUT",), tap_goto=1)
    done = FakeScreen("done", hierarchy_xml=hierarchy(node(text="Order placed")),
                      ocr_lines=("Order placed",))
    tc = {
        "name": "OCR tap", "package": "com.example.shop", "data": {},
        "steps": [
            {"action": "launch"},
            {"action": "tap", "target": {"ocr": "CHECKOUT"}},
            {"assert": {"type": "text_exists", "value": "Order placed"}},
        ],
    }
    _d, result = _run(tc, [promo, done], tmp_path)
    tap = result["results"][1]
    assert tap.status is Status.PASS
    assert tap.resolved_by == "ocr"
    assert tap.resolved_confidence and tap.resolved_confidence > 0.5
    assert result["overall"] == "PASS"


def test_blocked_target_skips_rest(tmp_path):
    screen = FakeScreen("stuck", hierarchy_xml=hierarchy(node(text="Home")),
                        ocr_lines=("Home",))
    tc = {
        "name": "Blocked", "package": "com.example.shop", "data": {},
        "steps": [
            {"action": "launch"},
            {"action": "tap", "target": {"text": "Ghost", "ocr": "Ghost"}},
            {"assert": {"type": "text_exists", "value": "Never"}},
        ],
    }
    _d, result = _run(tc, [screen], tmp_path)
    statuses = [r.status for r in result["results"]]
    assert statuses == [Status.PASS, Status.BLOCKED, Status.SKIPPED]
    assert result["overall"] == "BLOCKED"
    # recovery trace was recorded on the blocked step
    assert result["results"][1].recovery.attempts


def test_crash_detected_from_logcat(tmp_path):
    screen = FakeScreen("boom", hierarchy_xml=hierarchy(node(text="Home")),
                        ocr_lines=("Home",))
    tc = {
        "name": "Crash", "package": "com.example.shop", "data": {},
        "steps": [
            {"action": "launch"},
            {"assert": {"type": "text_exists", "value": "Home"}},
        ],
    }
    _d, result = _run(tc, [screen], tmp_path,
                      logcat="01-01 E AndroidRuntime: FATAL EXCEPTION: main")
    assert result["results"][0].status is Status.CRASH
    assert "FATAL EXCEPTION" in result["results"][0].crash_signature
    assert result["overall"] == "CRASH"
    assert result["results"][1].status is Status.SKIPPED
