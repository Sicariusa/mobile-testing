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


def _stub_words(ocr_mod, monkeypatch, words):
    entries = []
    for i, tok in enumerate(words):
        entries.append({"text": tok, "norm": ocr_mod._normalise(tok), "conf": 0.9,
                        "left": i * 50, "top": 0, "width": 40, "height": 20, "line": (0, 0, 0)})
    monkeypatch.setattr(ocr_mod, "_load_words", lambda path, backend=None: entries)


def test_ocr_single_token_is_whole_word(monkeypatch):
    # 'ok' must not match inside 'Facebook' (the audit's OCR false PASS).
    _stub_words(ocr, monkeypatch, ["Facebook"])
    assert ocr.ocr_find("x.png", "ok") == []
    found, _ = ocr.ocr_text_exists("x.png", "ok")
    assert found is False


def test_ocr_tolerates_trailing_punctuation(monkeypatch):
    _stub_words(ocr, monkeypatch, ["Payment", "Successful!"])
    assert ocr.ocr_find("x.png", "successful")
    assert ocr.ocr_find("x.png", "Payment Successful")


def test_ocr_resolver_does_not_mis_tap_substring(monkeypatch):
    # target 'Pay' must not match 'Repay'.
    _stub_words(ocr, monkeypatch, ["Repay"])
    assert ocr.best_match("x.png", "Pay") is None


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
