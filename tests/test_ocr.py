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


def test_default_backend_is_tesseract():
    from engine import config
    assert config.OCR_BACKEND == "tesseract"


def test_unknown_backend_raises(tmp_path):
    img = render_text(str(tmp_path / "s.png"), ["hi"])
    import pytest
    with pytest.raises(ValueError):
        ocr._load_words(img, backend="does-not-exist")


def test_load_words_is_memoized_per_screenshot(tmp_path, monkeypatch):
    # validator + evidence both OCR the same after.png; Tesseract must run once.
    img = render_text(str(tmp_path / "s.png"), ["Hello"])
    calls = {"n": 0}
    real = ocr._load_words_tesseract

    def counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(ocr, "_load_words_tesseract", counting)
    ocr._load_words_cached.cache_clear()
    ocr.ocr_find(img, "Hello")
    ocr.ocr_find(img, "Hello")
    assert calls["n"] == 1


def test_easyocr_backend_reports_clearly_when_missing(tmp_path):
    # Only meaningful when easyocr isn't installed: selecting it must raise an
    # actionable RuntimeError, not an obscure ImportError deep in the matcher.
    import importlib.util
    import pytest
    if importlib.util.find_spec("easyocr") is not None:
        pytest.skip("easyocr installed; missing-backend path not exercised")
    img = render_text(str(tmp_path / "s.png"), ["hi"])
    with pytest.raises(RuntimeError, match="easyocr"):
        ocr._load_words(img, backend="easyocr")
