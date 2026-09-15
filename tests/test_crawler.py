"""Auto-crawl — bounded discovery over a scripted screen graph, with no device.

The graph: home → catalog → product (a chain), plus a "Home" loop-back on
catalog, a "Logout" destructive control on home, and an "Open Web" control that
jumps to another package. A correct crawl captures home/catalog/product only.
"""
from __future__ import annotations

from engine.crawler import crawl
from engine.screen_library import ScreenLibrary

HOME = """<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
    <node class="android.widget.Button" text="Products" clickable="true" enabled="true" bounds="[0,100][1080,300]"/>
    <node class="android.widget.Button" text="Logout" clickable="true" enabled="true" bounds="[0,400][1080,600]"/>
    <node class="android.widget.Button" text="Open Web" clickable="true" enabled="true" bounds="[0,700][1080,900]"/>
  </node>
</hierarchy>"""

CATALOG = """<hierarchy>
  <node class="android.widget.LinearLayout" bounds="[0,0][1080,2000]">
    <node class="android.widget.Button" text="Backpack" clickable="true" enabled="true" bounds="[0,100][1080,300]"/>
    <node class="android.widget.Button" text="Home" clickable="true" enabled="true" bounds="[0,400][1080,600]"/>
  </node>
</hierarchy>"""

PRODUCT = """<hierarchy>
  <node class="android.widget.ScrollView" bounds="[0,0][1080,2000]">
    <node class="android.widget.TextView" text="Product Detail" clickable="false" enabled="true" bounds="[0,0][1080,200]"/>
  </node>
</hierarchy>"""

WEB = """<hierarchy>
  <node class="android.webkit.WebView" bounds="[0,0][1080,2000]"/>
</hierarchy>"""

# center → (target screen, target package)
NAV = {
    "home": (HOME, "com.demo", {(540, 200): ("catalog", "com.demo"),
                                (540, 800): ("web", "com.android.chrome")}),
    "catalog": (CATALOG, "com.demo", {(540, 200): ("product", "com.demo"),
                                      (540, 500): ("home", "com.demo")}),
    "product": (PRODUCT, "com.demo", {}),
    "web": (WEB, "com.android.chrome", {}),
}


class ScriptedDevice:
    def __init__(self):
        self.stack = ["home"]

    @property
    def _cur(self):
        return self.stack[-1]

    def launch(self, package, activity=None):
        self.stack = ["home"]

    def current_package(self):
        return NAV[self._cur][1]

    def current_activity(self):
        return f".{self._cur}"

    def dump_hierarchy(self):
        return NAV[self._cur][0]

    def keyboard_visible(self):
        return False

    def screenshot(self, path):
        return path

    def tap_xy(self, x, y):
        target = NAV[self._cur][2].get((x, y))
        if target:
            self.stack.append(target[0])

    def press_back(self):
        if len(self.stack) > 1:
            self.stack.pop()

    def invalidate(self):
        pass


def _crawl(tmp_path, max_screens):
    dev = ScriptedDevice()
    lib = ScreenLibrary("com.demo", base_dir=str(tmp_path))
    summary = crawl(dev, "com.demo", lib, max_screens=max_screens,
                    screenshots=False, sleep=lambda *_: None,
                    settle_fn=lambda *a, **k: True)
    return lib, summary


def test_crawl_captures_the_chain_and_respects_the_cap(tmp_path):
    lib, s = _crawl(tmp_path, max_screens=3)
    assert s["screens_captured"] == 3
    labels = [c["label"] for c in s["captured"]]
    assert labels == ["auto_1", "auto_2", "auto_3"]
    # three distinct screens actually in the library
    fps = {c["fingerprint"] for c in s["captured"]}
    assert len(fps) == 3
    assert len(lib.screens()) == 3


def test_crawl_from_current_screen_starts_where_the_app_is(tmp_path):
    # launch=False: begin from whatever screen is open (here: catalog, mid-app)
    # instead of relaunching to home. The FIRST capture is the current screen.
    dev = ScriptedDevice()
    dev.stack = ["catalog"]                       # already driven into the app
    lib = ScreenLibrary("com.demo", base_dir=str(tmp_path))
    s = crawl(dev, "com.demo", lib, max_screens=3, launch=False,
              screenshots=False, sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    activities = [c["activity"] for c in s["captured"]]
    assert activities[0] == ".catalog"            # started here, NOT relaunched to home
    assert ".product" in activities               # explored forward from catalog


def test_crawl_marks_the_start_screen_as_checkpoint(tmp_path):
    _, s = _crawl(tmp_path, max_screens=3)
    assert s["checkpoint"] is not None
    assert s["checkpoint"]["activity"] == ".home"       # started here
    assert s["captured"][0]["is_checkpoint"] is True
    assert sum(1 for c in s["captured"] if c["is_checkpoint"]) == 1


def test_crawl_never_taps_destructive_controls(tmp_path):
    _, s = _crawl(tmp_path, max_screens=5)
    assert "Logout" in s["skipped_destructive"]


def test_crawl_dedups_loops_and_skips_other_packages(tmp_path):
    # max 5, but only 3 real screens exist; the Home loop-back must not
    # re-capture, and the Open Web jump (other package) must not be captured.
    lib, s = _crawl(tmp_path, max_screens=5)
    assert s["screens_captured"] == 3
    activities = {c["activity"] for c in s["captured"]}
    assert activities == {".home", ".catalog", ".product"}


def test_crawl_cap_of_one_captures_only_the_start(tmp_path):
    _, s = _crawl(tmp_path, max_screens=1)
    assert s["screens_captured"] == 1
    assert s["captured"][0]["activity"] == ".home"


def test_crawl_cap_is_hard_limited_to_five(tmp_path):
    _, s = _crawl(tmp_path, max_screens=99)
    assert s["max_screens"] == 5


# --- root-escape guard: the live bug where Back left the app onto the launcher --
ROOT = """<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
    <node class="android.widget.Button" text="Info" clickable="true" enabled="true" bounds="[0,100][1080,300]"/>
  </node>
</hierarchy>"""
LAUNCHER = """<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
    <node class="android.widget.TextView" text="Search" clickable="true" enabled="true" bounds="[0,100][1080,300]"/>
  </node>
</hierarchy>"""


class RootEscapeDevice:
    """A single-screen app whose 'Info' button does not navigate, and where Back
    at the root escapes to the launcher (another package) — exactly the shape
    that made the buggy crawler capture the home screen and search."""
    def __init__(self):
        self.at_launcher = False

    def launch(self, package, activity=None):
        self.at_launcher = False

    def current_package(self):
        return "com.launcher" if self.at_launcher else "com.demo"

    def current_activity(self):
        return ".Launcher" if self.at_launcher else ".Root"

    def dump_hierarchy(self):
        return LAUNCHER if self.at_launcher else ROOT

    def keyboard_visible(self):
        return False

    def screenshot(self, path):
        return path

    def tap_xy(self, x, y):
        # 'Info' is a no-op (never navigates); launcher taps do nothing here
        pass

    def press_back(self):
        # Back at the app root escapes to the launcher (like real Android)
        if not self.at_launcher:
            self.at_launcher = True

    def invalidate(self):
        pass


# --- scroll-aware crawling ---------------------------------------------------
def _prod_xml(scroll):
    # A scrollable product screen whose ADD TO CART button is below the fold:
    # it only appears in the dump once scrolled (scroll >= 1).
    add = ('<node class="android.widget.Button" text="ADD TO CART" clickable="true" '
           'enabled="true" bounds="[0,1500][1080,1660]"/>') if scroll >= 1 else ""
    return f"""<hierarchy>
      <node class="androidx.core.widget.NestedScrollView" scrollable="true" bounds="[0,0][1080,2000]">
        <node class="android.widget.TextView" text="Backpack" clickable="false" enabled="true" bounds="[0,100][1080,300]"/>
        <node class="android.widget.TextView" text="$29.99" clickable="false" enabled="true" bounds="[0,1200][1080,1340]"/>
        {add}
      </node>
    </hierarchy>"""

ADDED = """<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
    <node class="android.widget.Button" text="REMOVE" clickable="true" enabled="true" bounds="[0,1500][1080,1660]"/>
  </node>
</hierarchy>"""


class ScrollProductDevice:
    """A product screen whose Add-to-cart is revealed only by scrolling; tapping
    it navigates to an 'added' screen. Tracks scroll calls."""
    def __init__(self):
        self.screen, self.scroll, self.scroll_calls = "prod", 0, 0

    def launch(self, p, a=None): self.screen, self.scroll = "prod", 0
    def current_package(self): return "com.demo"
    def current_activity(self): return "." + self.screen
    def dump_hierarchy(self): return _prod_xml(self.scroll) if self.screen == "prod" else ADDED
    def keyboard_visible(self): return False
    def screenshot(self, path): return path

    def tap_xy(self, x, y):
        if self.screen == "prod" and self.scroll >= 1 and (x, y) == (540, 1580):
            self.screen, self.scroll = "added", 0

    def scroll_forward(self):
        self.scroll_calls += 1
        if self.screen == "prod" and self.scroll < 2:
            self.scroll += 1

    def press_back(self):
        if self.screen == "added": self.screen, self.scroll = "prod", 0
    def invalidate(self): pass


def test_scroll_reveals_below_fold_control_and_captures_result(tmp_path):
    dev = ScrollProductDevice()
    lib = ScreenLibrary("com.demo", base_dir=str(tmp_path))
    s = crawl(dev, "com.demo", lib, max_screens=3, launch=False, screenshots=False,
              sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    acts = [c["activity"] for c in s["captured"]]
    # (a) the below-fold Add-to-cart was revealed, tapped, and its screen captured
    assert ".added" in acts
    # (c) intermediate scroll positions are NOT captured — only prod + added
    assert acts.count(".prod") == 1
    assert s["screens_captured"] == 2
    assert len({c["fingerprint"] for c in s["captured"]}) == 2


class NoChangeScrollDevice:
    """Scrollable, but scrolling never changes the view (already at the bottom)."""
    def __init__(self): self.scroll_calls = 0
    def launch(self, p, a=None): pass
    def current_package(self): return "com.demo"
    def current_activity(self): return ".only"
    def dump_hierarchy(self):
        return ('<hierarchy><node class="ScrollView" scrollable="true" bounds="[0,0][1080,2000]">'
                '<node class="TextView" text="static" clickable="false" bounds="[0,0][1080,100]"/>'
                '</node></hierarchy>')
    def keyboard_visible(self): return False
    def screenshot(self, p): return p
    def tap_xy(self, x, y): pass
    def scroll_forward(self): self.scroll_calls += 1
    def press_back(self): pass
    def invalidate(self): pass


def test_scroll_stops_when_view_does_not_change(tmp_path):
    dev = NoChangeScrollDevice()
    lib = ScreenLibrary("com.demo", base_dir=str(tmp_path))
    s = crawl(dev, "com.demo", lib, max_screens=3, launch=False, screenshots=False,
              sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    # (b) it tried one scroll, saw no change, and stopped — no runaway
    assert dev.scroll_calls == 1
    assert s["screens_captured"] == 1


class NoScrollableDevice:
    """One screen, a single no-op button, NO scrollable container."""
    def __init__(self): self.scroll_calls = 0
    def launch(self, p, a=None): pass
    def current_package(self): return "com.demo"
    def current_activity(self): return ".flat"
    def dump_hierarchy(self):
        return ('<hierarchy><node class="FrameLayout" bounds="[0,0][1080,2000]">'
                '<node class="Button" text="Info" clickable="true" enabled="true" bounds="[0,100][1080,300]"/>'
                '</node></hierarchy>')
    def keyboard_visible(self): return False
    def screenshot(self, p): return p
    def tap_xy(self, x, y): pass
    def scroll_forward(self): self.scroll_calls += 1
    def press_back(self): pass
    def invalidate(self): pass


def test_no_scroll_when_no_scrollable_container(tmp_path):
    dev = NoScrollableDevice()
    lib = ScreenLibrary("com.demo", base_dir=str(tmp_path))
    crawl(dev, "com.demo", lib, max_screens=3, launch=False, screenshots=False,
          sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    # (d) never scrolled a screen with no scrollable container
    assert dev.scroll_calls == 0


def test_backtracking_taps_remaining_parent_candidates(tmp_path):
    # (e) after exploring the first child, the sibling candidate is still tapped.
    dev = ScriptedDevice()
    dev.stack = ["catalog"]                 # catalog has Backpack->product and Home->home
    lib = ScreenLibrary("com.demo", base_dir=str(tmp_path))
    s = crawl(dev, "com.demo", lib, max_screens=5, launch=False, screenshots=False,
              sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    acts = {c["activity"] for c in s["captured"]}
    # explored Backpack->product (child 1) AND still went Home->home (sibling)
    assert ".product" in acts and ".home" in acts


def test_crawl_does_not_escape_to_the_launcher(tmp_path):
    dev = RootEscapeDevice()
    lib = ScreenLibrary("com.demo", base_dir=str(tmp_path))
    s = crawl(dev, "com.demo", lib, max_screens=3, screenshots=False,
              sleep=lambda *_: None, settle_fn=lambda *a, **k: True)
    # only the app's own screen is captured; the launcher/search never is
    assert s["screens_captured"] == 1
    assert s["captured"][0]["activity"] == ".Root"
    assert all(c["activity"] != ".Launcher" for c in s["captured"])
    assert dev.at_launcher is False   # a no-nav tap must not have pressed Back
