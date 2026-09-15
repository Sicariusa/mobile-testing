"""Engine performance & correctness checks — the reusable core of the harness.

Every check returns a ``Check`` (name, ok, detail, plus timing/verdict where
relevant). ``tools/harness.py`` prints them; ``tests/test_performance.py`` asserts
them, so a complexity regression fails CI. Timings use the *minimum* of several
runs (least noise) and only assert scaling *ratios*, never absolute wall-clock —
so the guards hold on any machine.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from engine import config
from engine import inspect as ins
from engine.device import AndroidDevice


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    verdict: str = ""


# --- timing ------------------------------------------------------------------
def _best_ns(fn: Callable[[], object], repeat: int = 5) -> int:
    best = None
    for _ in range(repeat):
        t = time.perf_counter_ns()
        fn()
        dt = time.perf_counter_ns() - t
        best = dt if best is None else min(best, dt)
    return best or 1


def _hierarchy(n: int) -> str:
    nodes = "".join(
        f'<node resource-id="id/x{i}" class="android.widget.TextView" '
        f'text="Item {i}" content-desc="d{i}" clickable="true" '
        f'bounds="[0,{i * 5}][100,{i * 5 + 40}]"/>'
        for i in range(n))
    return f'<hierarchy rotation="0">{nodes}</hierarchy>'


def _classify(ratio: float, n_ratio: float) -> str:
    """Empirical big-O bucket from a size jump and its time jump."""
    if ratio <= n_ratio * 1.6:
        return "O(n)"
    if ratio <= n_ratio * 4:
        return "~O(n log n)"
    if ratio <= (n_ratio ** 2) * 1.6:
        return "O(n^2)  ⚠"
    return "worse than n^2  ⚠"


def _scaling_check(name: str, make, work, small=500, big=5000,
                   budget_mult=4.0) -> Check:
    """Assert `work` scales no worse than ~O(n log n): time ratio for a `big/small`
    size jump stays within `budget_mult` × the size ratio."""
    a, b = make(small), make(big)
    ta, tb = _best_ns(lambda: work(a)), _best_ns(lambda: work(b))
    ratio = tb / max(ta, 1)
    n_ratio = big / small
    ok = ratio <= n_ratio * budget_mult
    verdict = _classify(ratio, n_ratio)
    return Check(name, ok,
                 f"n {small}->{big} ({n_ratio:.0f}x): time {ratio:.1f}x  [{verdict}]",
                 verdict)


# --- algorithmic complexity --------------------------------------------------
def check_parse_elements_linear() -> Check:
    return _scaling_check("parse_elements", _hierarchy, ins.parse_elements)


def check_rank_candidates_linear() -> Check:
    def make(n):
        return ins.parse_elements(_hierarchy(n))
    return _scaling_check("rank_candidates", make,
                          lambda els: ins.rank_candidates("Item 42", els,
                                                          role="tappable"))


def check_structural_fingerprint() -> Check:
    def make(n):
        return ins.parse_elements(_hierarchy(n))
    return _scaling_check("structural_fingerprint", make,
                          lambda els: ins.structural_fingerprint(".Main", els))


# --- device efficiency (the hierarchy memo) ----------------------------------
class _StubU2:
    def __init__(self):
        self.dumps = 0
        self._xml = "<hierarchy><node text='A'/></hierarchy>"

    def dump_hierarchy(self):
        self.dumps += 1
        return self._xml

    def app_current(self):
        return {"activity": ".Main", "package": "app"}

    def click(self, x, y):
        self._xml = "<hierarchy><node text='B'/></hierarchy>"

    def send_keys(self, v): pass
    def press(self, k): pass
    def swipe(self, *a, **k): pass


def check_hierarchy_memo_o1() -> Check:
    """Within one screen state, K reads issue ONE real dump — O(1) for every
    consumer (resolve/recovery/validation) after the first. A mutating action
    invalidates it (so change is never missed)."""
    prev = config.HIERARCHY_CACHE
    config.HIERARCHY_CACHE = True
    try:
        d = AndroidDevice(_StubU2(), serial="stub")
        for _ in range(20):
            d.dump_hierarchy()
        reads = d._d.dumps            # 20 reads
        d.tap_xy(1, 1)                # mutate -> invalidate
        d.dump_hierarchy()
        after = d._d.dumps
        ok = reads == 1 and after == 2
        return Check("hierarchy memo (O(1) reads)", ok,
                     f"20 reads -> {reads} dump; +1 action -> {after} dumps",
                     "O(1)")
    finally:
        config.HIERARCHY_CACHE = prev


# --- crawl device-op bound ---------------------------------------------------
class _Counter:
    """Wraps a device, counting the expensive I/O calls."""
    def __init__(self, inner):
        self._inner = inner
        self.counts: dict[str, int] = {}

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if callable(attr) and name in (
                "dump_hierarchy", "screenshot", "tap_xy", "scroll_forward",
                "swipe", "press_back"):
            def wrapped(*a, **k):
                self.counts[name] = self.counts.get(name, 0) + 1
                return attr(*a, **k)
            return wrapped
        return attr


_H = ("home", "catalog", "product")
_XML = {
    "home": '<hierarchy><node class="V" scrollable="false" bounds="[0,0][100,100]">'
            '<node class="B" text="Products" clickable="true" bounds="[0,10][100,30]"/>'
            '</node></hierarchy>',
    "catalog": '<hierarchy><node class="V"><node class="B" text="Backpack" '
               'clickable="true" bounds="[0,10][100,30]"/></node></hierarchy>',
    "product": '<hierarchy><node class="V"><node class="T" text="Detail" '
               'clickable="false" bounds="[0,0][100,20]"/></node></hierarchy>',
}
_NAV = {"home": {(50, 20): "catalog"}, "catalog": {(50, 20): "product"},
        "product": {}}


class _Scripted:
    def __init__(self):
        self.stack = ["home"]

    def launch(self, p, a=None): self.stack = ["home"]
    def current_package(self): return "com.demo"
    def current_activity(self): return "." + self.stack[-1]
    def dump_hierarchy(self): return _XML[self.stack[-1]]
    def keyboard_visible(self): return False
    def screenshot(self, path): return path

    def tap_xy(self, x, y):
        t = _NAV[self.stack[-1]].get((x, y))
        if t:
            self.stack.append(t)

    def scroll_forward(self): pass
    def swipe(self, *a, **k): pass
    def press_back(self):
        if len(self.stack) > 1:
            self.stack.pop()
    def invalidate(self): pass


def check_crawl_bounded() -> Check:
    """A crawl's device I/O is bounded by the screen/tap budget — no runaway.
    Correctness: it captures the whole 3-screen chain."""
    from engine.crawler import crawl
    from engine.screen_library import ScreenLibrary
    import tempfile
    dev = _Counter(_Scripted())
    with tempfile.TemporaryDirectory() as tmp:
        lib = ScreenLibrary("com.demo", base_dir=tmp)
        s = crawl(dev, "com.demo", lib, max_screens=3, launch=False,
                  screenshots=False, sleep=lambda *_: None,
                  settle_fn=lambda *a, **k: True)
    dumps = dev.counts.get("dump_hierarchy", 0)
    taps = dev.counts.get("tap_xy", 0)
    # generous but finite bound: a few dumps per screen visit + per tap
    bound = 12 * s["max_screens"] + 6 * max(taps, 1)
    ok = s["screens_captured"] == 3 and dumps <= bound
    return Check("crawl device-ops bounded", ok,
                 f"captured {s['screens_captured']}/3, {dumps} dumps, "
                 f"{taps} taps (<= {bound})", "bounded")


# --- correctness smoke -------------------------------------------------------
def check_run_smoke() -> Check:
    """The whole runner passes a happy-path flow end to end on a FakeDevice —
    proof the harness exercises the real engine, not a mock of it."""
    from tests.fake_device import FakeDevice, FakeScreen, hierarchy, node
    from engine.runner import run
    import tempfile
    login = FakeScreen(
        name="login", hierarchy_xml=hierarchy(
            node(resource_id="id/user", text="", clickable="true",
                 **{"class": "android.widget.EditText"}, bounds="[0,0][100,20]"),
        ), ocr_lines=("Login",),
        elements=({"id": "id/user", "center": (50, 10), "goto": 1},))
    home = FakeScreen(name="home", hierarchy_xml=hierarchy(
        node(text="Welcome", bounds="[0,0][100,20]")), ocr_lines=("Welcome",))
    tc = {"name": "smoke", "package": "com.example.shop", "steps": [
        {"action": "tap", "target": {"id": "id/user"}},
        {"assert": {"type": "text_exists", "value": "Welcome"}},
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        res = run(tc, FakeDevice([login, home]), base_dir=tmp,
                  sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    ok = res["overall"] == "PASS"
    return Check("runner end-to-end (FakeDevice)", ok,
                 f"overall={res['overall']} counts={res['counts']}")


ALL_CHECKS = (
    check_run_smoke,
    check_hierarchy_memo_o1,
    check_parse_elements_linear,
    check_rank_candidates_linear,
    check_structural_fingerprint,
    check_crawl_bounded,
)


def run_all() -> list[Check]:
    return [c() for c in ALL_CHECKS]
