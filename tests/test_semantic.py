"""Phase 3 — semantic actions: string (intent) targets, enter_text, submit."""
from __future__ import annotations

from engine import executor, models
from engine.models import Status
from tests.fake_device import FakeDevice, FakeScreen

LOGIN_XML = (
    "<hierarchy><node class='android.widget.FrameLayout' bounds='[0,0][1080,2400]'>"
    "<node resource-id='app:id/email' class='android.widget.EditText' "
    "content-desc='Email' bounds='[0,100][1000,200]'/>"
    "<node resource-id='app:id/login' class='android.widget.Button' text='Login' "
    "clickable='true' bounds='[0,300][1000,400]'/>"
    "</node></hierarchy>")
ELEMENTS = (
    {"id": "app:id/email", "center": (500, 150)},
    {"id": "app:id/login", "text": "Login", "center": (500, 350)},
)
NOSLEEP = lambda *_a, **_k: None


def _dev():
    return FakeDevice([FakeScreen("login", hierarchy_xml=LOGIN_XML, elements=ELEMENTS)])


def _run(step, tmp_path):
    return executor.execute(_dev(), step, package="app",
                            before_path=str(tmp_path / "b.png"),
                            after_path=str(tmp_path / "a.png"), sleep=NOSLEEP)


def test_string_target_is_intent_label(tmp_path):
    res = _run({"action": "tap", "target": "Login"}, tmp_path)
    assert res.status is Status.PASS
    assert res.resolved_by == models.STRATEGY_RANKED


def test_enter_text_types_into_labelled_field(tmp_path):
    d = _dev()
    res = executor.execute(d, {"action": "enter_text", "target": "Email", "value": "hi@x.com"},
                           package="app", before_path=str(tmp_path / "b.png"),
                           after_path=str(tmp_path / "a.png"), sleep=NOSLEEP)
    assert res.status is Status.PASS
    assert "hi@x.com" in d.typed


def test_submit_finds_a_submit_button_without_target(tmp_path):
    res = _run({"action": "submit"}, tmp_path)
    assert res.status is Status.PASS          # matched "Login" from SUBMIT_LABELS
    assert res.resolved_by == models.STRATEGY_RANKED
