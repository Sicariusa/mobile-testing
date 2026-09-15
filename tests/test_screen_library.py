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


def test_records_get_a_stable_immutable_id(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    rec = lib.add(_obs(".Catalog", CATALOG_XML), "catalog")
    assert rec["id"].startswith("scr_")
    # re-capturing the same label keeps the SAME id (stable handle)
    rec2 = lib.add(_obs(".Catalog", CATALOG_XML), "catalog")
    assert rec2["id"] == rec["id"]
    assert len(lib.screens()) == 1


def test_remove_and_rename_operate_by_id(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    a = lib.add(_obs(".A", CATALOG_XML), "product")["id"]
    b = lib.add(_obs(".B", CATALOG_XML.replace("Backpack", "Onesie")), "screen")["id"]
    assert a != b
    # rename by id — label changes, id and count unchanged
    assert lib.rename(a, "catalog") is True
    assert lib.get(a)["label"] == "catalog"
    assert lib.rename("scr_missing", "x") is False
    # remove by id — only that record goes, even after a duplicate label
    assert lib.remove(b) is True
    assert lib.remove(b) is False
    assert [s["label"] for s in lib.screens()] == ["catalog"]
    assert lib.get(a) is not None


def test_legacy_entry_without_id_is_migrated(tmp_path):
    import json, os
    d = tmp_path / "com.example.shop"
    d.mkdir()
    (d / "library.json").write_text(json.dumps({
        "package": "com.example.shop",
        "screens": [{"label": "old", "structural_fingerprint": "abc", "elements": []}],
    }), encoding="utf-8")
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    assert lib.screens()[0]["id"].startswith("scr_")
    # migration persisted, so a reload keeps the same id
    same_id = lib.screens()[0]["id"]
    lib2 = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    assert lib2.screens()[0]["id"] == same_id


def test_checkpoint_flag_set_toggle_and_preserved(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    a = lib.add(_obs(".A", CATALOG_XML), "start", checkpoint=True)
    assert a["is_checkpoint"] is True
    b = lib.add(_obs(".B", CATALOG_XML.replace("Backpack", "X")), "other")
    assert b["is_checkpoint"] is False
    # toggle by id
    assert lib.set_checkpoint(b["id"], True) is True
    assert lib.get(b["id"])["is_checkpoint"] is True
    assert lib.set_checkpoint("scr_nope", True) is False
    # re-capturing a checkpoint label keeps the flag
    a2 = lib.add(_obs(".A", CATALOG_XML), "start")
    assert a2["is_checkpoint"] is True


def test_duplicates_flags_shared_fingerprints_only(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    lib.add(_obs(".Same", CATALOG_XML), "one")
    lib.add(_obs(".Same", CATALOG_XML), "two")            # identical fingerprint
    lib.add(_obs(".Other", CATALOG_XML.replace("Backpack", "Bike")), "three")
    dupes = lib.duplicates()
    assert len(dupes) == 1                                # only the shared fp
    ids = next(iter(dupes.values()))
    assert len(ids) == 2


def test_clickable_ancestor_promotion_ranks_the_card():
    # ranking "Backpack" (a non-clickable title) for a tap must surface the
    # clickable card ancestor, not only the rejected title.
    els = inspect_mod.parse_elements(CATALOG_XML)
    cands = inspect_mod.rank_candidates("Sauce Labs Backpack", els, role="tappable")
    assert cands, "expected at least one candidate"
    top = cands[0]
    assert top.element.clickable, "top tappable candidate should be clickable"
