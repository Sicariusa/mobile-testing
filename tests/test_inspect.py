"""Perception layer: element parsing, fingerprints, screen diff, candidate
ranking, and break-time diagnostics — all deterministic, no device."""
from __future__ import annotations

from engine import inspect as inspect_mod
from engine.models import FailureReason, Observation, Status
from engine import executor
from tests.fake_device import FakeDevice, FakeScreen

LOGIN_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node index="0" resource-id="app:id/email" class="android.widget.EditText"
          text="" content-desc="Email" clickable="true" enabled="true"
          bounds="[40,100][1040,200]"/>
    <node index="1" resource-id="app:id/password" class="android.widget.EditText"
          password="true" clickable="true" enabled="true" bounds="[40,220][1040,320]"/>
    <node index="2" resource-id="app:id/login" class="android.widget.Button"
          text="Login" clickable="true" enabled="true" bounds="[40,400][1040,500]"/>
  </node>
</hierarchy>"""

HOME_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" resource-id="app:id/welcome" class="android.widget.TextView"
        text="Welcome" bounds="[40,100][1040,200]"/>
</hierarchy>"""


def _obs(activity, xml, keyboard=False):
    return Observation(timestamp=0.0, package="app", activity=activity,
                       hierarchy_xml=xml, keyboard_visible=keyboard)


def test_parse_elements_attributes_and_bounds():
    els = inspect_mod.parse_elements(LOGIN_XML)
    interesting = inspect_mod.interesting(els)
    assert len(interesting) == 3
    email = next(e for e in els if e.resource_id == "app:id/email")
    login = next(e for e in els if e.resource_id == "app:id/login")
    assert email.editable and email.kind() == "field"
    assert not login.editable and login.clickable and login.kind() == "button"
    assert login.center() == (540, 450)          # from bounds [40,400][1040,500]
    assert email.depth == 2                        # frame(1) -> field(2)


def test_parse_elements_malformed_is_empty():
    assert inspect_mod.parse_elements("<not-xml") == []
    assert inspect_mod.parse_elements(None) == []


def test_structural_vs_content_fingerprint():
    before = _obs("Login", LOGIN_XML)
    # same structure (same ids/classes/descs), only a text value changes
    err = _obs("Login", LOGIN_XML.replace('text=""', 'text="Invalid"', 1))
    assert before.structural_fingerprint() == err.structural_fingerprint()
    assert before.content_fingerprint() != err.content_fingerprint()


def test_screen_diff_navigation_and_content():
    login, home = _obs("LoginActivity", LOGIN_XML), _obs("HomeActivity", HOME_XML)
    nav = inspect_mod.screen_diff(login, home)
    assert nav.summary == "NAVIGATION_DETECTED"
    assert nav.activity_changed and "Welcome" in nav.added_text

    before = _obs("LoginActivity", LOGIN_XML)
    after = _obs("LoginActivity", LOGIN_XML.replace('text=""', 'text="Invalid"', 1))
    content = inspect_mod.screen_diff(before, after)
    assert content.summary == "CONTENT_CHANGED"
    assert not content.activity_changed


def test_rank_candidates_prefers_right_element_and_role():
    els = inspect_mod.parse_elements(LOGIN_XML)
    top_login = inspect_mod.rank_candidates("Login", els, role="tappable")[0]
    assert top_login.element.resource_id == "app:id/login"
    top_email = inspect_mod.rank_candidates("Email", els, role="field")[0]
    assert top_email.element.resource_id == "app:id/email"


def test_blocked_step_reports_reason_and_suggestions(tmp_path):
    # a screen that has a near-miss button but not the requested target
    xml = ("<hierarchy><node resource-id='app:id/signin' class='android.widget.Button' "
           "text='Sign In' clickable='true' bounds='[0,0][100,100]'/></hierarchy>")
    d = FakeDevice([FakeScreen("s", hierarchy_xml=xml, ocr_lines=(), elements=())])
    res = executor.execute(
        d, {"action": "tap", "target": {"text": "Login"}},
        package="app", before_path=str(tmp_path / "b.png"),
        after_path=str(tmp_path / "a.png"), sleep=lambda *_a, **_k: None,
    )
    assert res.status is Status.BLOCKED
    assert res.failure_reason == FailureReason.TARGET_NOT_FOUND
    assert res.screen_summary is not None
    assert any(c["resource_id"] == "app:id/signin" for c in res.suggestions)
