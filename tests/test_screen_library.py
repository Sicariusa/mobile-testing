"""ScreenLibrary — capture, structural match, off-screen bearing, persistence.
Also covers the clickable-ancestor promotion the library relies on."""
from __future__ import annotations

from engine import inspect as inspect_mod
from engine.models import Observation
from engine.screen_library import ScreenLibrary

# A catalog row: the product TITLE is non-clickable; its CARD ancestor is
# clickable but carries no text — the SwagLabs shape that motivated the fix.
CATALOG_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" class="androidx.recyclerview.widget.RecyclerView" bounds="[0,0][1080,2400]">
    <node index="0" class="android.view.ViewGroup" clickable="true" enabled="true"
          bounds="[0,200][1080,900]">
      <node index="0" class="android.widget.TextView" text="Sauce Labs Backpack"
            clickable="false" enabled="true" bounds="[40,300][900,380]"/>
      <node index="1" class="android.widget.Button" content-desc="test-ADD TO CART"
            text="ADD TO CART" clickable="true" enabled="true" bounds="[40,700][900,860]"/>
    </node>
  </node>
</hierarchy>"""


def _obs(activity, xml):
    return Observation(timestamp=0.0, package="com.example.shop",
                       activity=activity, hierarchy_xml=xml)


def test_capture_match_and_reload(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    obs = _obs(".Catalog", CATALOG_XML)
    entry = lib.add(obs, "catalog")
    lib.save()

    fp = obs.structural_fingerprint()
    assert entry["structural_fingerprint"] == fp
    assert lib.match(fp)["label"] == "catalog"
    assert lib.match("nope") is None

    # reload from disk → same entry survives
    lib2 = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    assert lib2.match(fp)["label"] == "catalog"
    assert len(lib2.screens()) == 1


def test_recapture_replaces_same_label(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    lib.add(_obs(".Catalog", CATALOG_XML), "catalog")
    lib.add(_obs(".Catalog", CATALOG_XML), "catalog")
    assert len(lib.screens()) == 1


def test_find_bearing_points_at_captured_control(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    lib.add(_obs(".Catalog", CATALOG_XML), "catalog")
    bearing = lib.find_bearing("add to cart", role="tappable")
    assert bearing is not None
    assert bearing["label"] == "catalog"
    # center of the ADD TO CART button bounds [40,700][900,860]
    assert bearing["center"] == (470, 780)


def test_clickable_ancestor_promotion_ranks_the_card():
    # ranking "Backpack" (a non-clickable title) for a tap must surface the
    # clickable card ancestor, not only the rejected title.
    els = inspect_mod.parse_elements(CATALOG_XML)
    cands = inspect_mod.rank_candidates("Sauce Labs Backpack", els, role="tappable")
    assert cands, "expected at least one candidate"
    top = cands[0]
    assert top.element.clickable, "top tappable candidate should be clickable"
