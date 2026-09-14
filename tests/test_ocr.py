"""OCR runs for real against rendered screenshots (Tesseract required)."""
from __future__ import annotations

import os

from engine import ocr
from tests.fake_device import render_text


def test_ocr_find_returns_bounds(tmp_path):
    img = render_text(str(tmp_path / "s.png"), ["Welcome back", "PAY NOW"])
    matches = ocr.ocr_find(img, "PAY NOW")
    assert matches, "expected to find 'PAY NOW'"
    best = matches[0]
    assert best["confidence"] > 0.5
    b = best["bounds"]
    # sane bounds with a usable tap center
    assert b["right"] > b["left"] and b["bottom"] > b["top"]
    cx, cy = b["center"]
    assert 0 < cx < 600 and 0 < cy < 900


def test_ocr_text_exists_hit_and_miss(tmp_path):
    img = render_text(str(tmp_path / "s.png"), ["Checkout complete"])
    found, conf = ocr.ocr_text_exists(img, "Checkout complete")
    assert found and conf >= 0.6
    missing, _ = ocr.ocr_text_exists(img, "Totally absent phrase")
    assert missing is False


def test_ocr_is_case_insensitive(tmp_path):
    img = render_text(str(tmp_path / "s.png"), ["Login"])
    found, _ = ocr.ocr_text_exists(img, "login")
    assert found
