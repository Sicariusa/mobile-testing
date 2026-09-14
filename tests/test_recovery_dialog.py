"""Phase 5 — recovery detects a blocking dialog, dismisses it, and re-resolves."""
from __future__ import annotations

from engine import recovery
from tests.fake_device import FakeDevice, FakeScreen

NOSLEEP = lambda *_a, **_k: None

DIALOG_XML = (
    "<hierarchy><node class='android.app.Dialog' bounds='[0,0][1080,2400]'>"
    "<node class='android.widget.Button' text='Allow' clickable='true' "
    "bounds='[0,0][200,100]'/></node></hierarchy>")


def test_dialog_is_dismissed_then_target_resolved():
    dialog = FakeScreen("perm", hierarchy_xml=DIALOG_XML,
                        elements=({"text": "Allow", "center": (100, 50), "goto": 1},))
    main = FakeScreen("main",
                      elements=({"text": "Continue", "center": (100, 400), "goto": 1},))
    d = FakeDevice([dialog, main])

    res, trace = recovery.reach(d, {"text": "Continue"}, sleep=NOSLEEP)
    assert res is not None and res.found
    methods = [(a["method"], a["outcome"]) for a in trace.attempts]
    assert ("dismiss_dialog", "tapped") in [(m, o) for m, o in methods]
    assert ("post_dialog", "resolved") in [(m, o) for m, o in methods]
