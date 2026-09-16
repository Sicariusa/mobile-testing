"""Atomic JSON persistence (audit S1): no partial files, failures propagate."""
from __future__ import annotations

import json
import os

import pytest

from engine import atomicio
from engine.screen_library import ScreenLibrary


def test_write_json_atomic_round_trips_and_leaves_no_temp(tmp_path):
    path = str(tmp_path / "sub" / "data.json")
    atomicio.write_json_atomic(path, {"a": 1})
    assert json.load(open(path, encoding="utf-8")) == {"a": 1}
    leftovers = [p for p in os.listdir(tmp_path / "sub") if p.endswith(".tmp")]
    assert leftovers == []


def test_write_json_atomic_propagates_and_cleans_up_on_error(tmp_path):
    path = str(tmp_path / "data.json")
    with pytest.raises(TypeError):        # sets are not JSON serialisable
        atomicio.write_json_atomic(path, {"bad": {1, 2, 3}})
    assert not os.path.exists(path)       # nothing partial left behind
    assert [p for p in os.listdir(tmp_path) if p.endswith(".tmp")] == []


def test_screen_library_save_is_atomic(tmp_path):
    lib = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    lib.data["screens"].append({"id": "scr_x", "label": "home"})
    lib.save()
    reloaded = ScreenLibrary("com.example.shop", base_dir=str(tmp_path))
    assert any(s["id"] == "scr_x" for s in reloaded.screens())


def test_screen_library_package_cannot_escape_base_dir(tmp_path):
    base = tmp_path / "screens"
    lib = ScreenLibrary("..", base_dir=str(base))
    resolved = os.path.realpath(lib.dir)
    assert resolved.startswith(os.path.realpath(str(base)))


def test_safe_dirname_rejects_parent_escape():
    assert atomicio.safe_dirname("..") == "app"
    assert atomicio.safe_dirname(".") == "app"
    assert atomicio.safe_dirname("com.example.shop") == "com.example.shop"
    assert atomicio.safe_dirname("a/b\\c") == "a_b_c"
