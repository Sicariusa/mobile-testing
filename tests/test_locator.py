"""Phase 2 — candidate-ranked target resolution + self-healing selector cache.

Label-based targets (no explicit id/text) resolve by scoring the live inventory
and cache their concrete binding per screen.
"""
from __future__ import annotations

from engine import resolver, inspect as I, models
from engine.selector_cache import SelectorCache
from tests.fake_device import FakeDevice, FakeScreen

LOGIN_XML = (
    "<hierarchy><node class='android.widget.FrameLayout' bounds='[0,0][1080,2400]'>"
    "<node resource-id='app:id/email' class='android.widget.EditText' "
    "content-desc='Email' bounds='[0,100][1000,200]'/>"
    "<node resource-id='app:id/login' class='android.widget.Button' "
    "text='Login' clickable='true' bounds='[0,300][1000,400]'/>"
    "</node></hierarchy>")

LOGIN_ELEMENTS = (
    {"id": "app:id/email", "center": (500, 150)},
    {"id": "app:id/login", "text": "Login", "center": (500, 350)},
)


def _login_device():
    return FakeDevice([FakeScreen("login", hierarchy_xml=LOGIN_XML,
                                  elements=LOGIN_ELEMENTS)])


def _fp():
    return I.structural_fingerprint("com.example.shop/.MainActivity",
                                    I.parse_elements(LOGIN_XML))


def test_label_field_resolves_by_ranking():
    d = _login_device()
    res = resolver.resolve(d, {"label": "Email"}, role="field")
    assert res.found and res.status == models.RESOLVE_MATCHED
    assert res.strategy == models.STRATEGY_RANKED
    assert res.bound_selector["value"] == "app:id/email"


def test_label_button_resolves_by_ranking():
    d = _login_device()
    res = resolver.resolve(d, {"label": "Login"}, role="tappable")
    assert res.found and res.strategy == models.STRATEGY_RANKED
    assert res.bound_selector["value"] == "app:id/login"


def test_cache_learns_then_hits(tmp_path):
    d = _login_device()
    cache = SelectorCache("com.example.shop", base_dir=str(tmp_path))
    r1 = resolver.resolve(d, {"label": "Email"}, role="field", cache=cache)
    assert r1.found and cache.bindings()
    r2 = resolver.resolve(d, {"label": "Email"}, role="field", cache=cache)
    assert r2.found and r2.status == models.RESOLVE_MATCHED
    assert any(a["method"] == "cache" and a["outcome"] == "hit" for a in r2.attempts)


def test_cache_self_heals_stale_binding(tmp_path):
    d = _login_device()
    cache = SelectorCache("com.example.shop", base_dir=str(tmp_path))
    cache.put(_fp(), "field", "Email",
              {"strategy": models.STRATEGY_RESOURCE_ID, "value": "app:id/GONE"})
    res = resolver.resolve(d, {"label": "Email"}, role="field", cache=cache)
    assert res.found and res.strategy == models.STRATEGY_RANKED  # rebound, not stale
    assert any(a["method"] == "cache" and a["outcome"] == "stale" for a in res.attempts)


def test_ambiguous_when_two_equal_candidates():
    xml = ("<hierarchy>"
           "<node resource-id='app:id/a' class='android.widget.Button' text='Submit' "
           "clickable='true' bounds='[0,0][100,100]'/>"
           "<node resource-id='app:id/b' class='android.widget.Button' text='Submit' "
           "clickable='true' bounds='[0,200][100,300]'/>"
           "</hierarchy>")
    d = FakeDevice([FakeScreen("s", hierarchy_xml=xml, elements=(
        {"id": "app:id/a", "text": "Submit", "center": (50, 50)},
        {"id": "app:id/b", "text": "Submit", "center": (50, 250)},
    ))])
    res = resolver.resolve(d, {"label": "Submit"}, role="tappable")
    assert res.found and res.status == models.RESOLVE_AMBIGUOUS
    assert len(res.candidates) >= 2


def test_explicit_selector_still_exact():
    d = _login_device()
    res = resolver.resolve(d, {"id": "app:id/login"})
    assert res.found and res.status == models.RESOLVE_EXACT
    assert res.strategy == models.STRATEGY_RESOURCE_ID
