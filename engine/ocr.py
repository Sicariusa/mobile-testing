"""OCR perception — read text off a screenshot with Tesseract.

Used two ways:
  * as the resolver's last-resort way to *locate* a tappable label the
    accessibility tree never exposes (returns bounds -> tap center);
  * as the validator's way to *confirm* visible text the hierarchy missed.

Matching is normalised (case-insensitive, whitespace-collapsed) and supports
multi-word phrases by reconstructing each OCR line and sliding a word window,
so "PAY NOW" matches even though Tesseract returns two word boxes.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Optional

from .config import OCR_BACKEND, OCR_MIN_CONFIDENCE


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _tokens(s: str) -> list[str]:
    return _normalise(s).split()


def _load_words(image_path: str, backend: Optional[str] = None) -> list[dict[str, Any]]:
    """Return per-word OCR entries (normalised text, confidence 0..1, bounds and
    a stable line id) from the configured backend. Backends are imported lazily,
    so this module imports fine whether or not either engine is installed.
    """
    backend = backend or OCR_BACKEND
    if backend == "tesseract":
        return _load_words_tesseract(image_path)
    if backend == "easyocr":
        return _load_words_easyocr(image_path)
    raise ValueError(f"unknown OCR_BACKEND: {backend!r} (use 'tesseract' or 'easyocr')")


def _load_words_tesseract(image_path: str) -> list[dict[str, Any]]:
    import pytesseract
    from PIL import Image

    with Image.open(image_path) as img:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    words: list[dict[str, Any]] = []
    n = len(data["text"])
    for i in range(n):
        raw = data["text"][i]
        if not raw or not raw.strip():
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:
            continue
        words.append({
            "text": raw.strip(),
            "norm": _normalise(raw),
            "conf": conf / 100.0,
            "left": int(data["left"][i]),
            "top": int(data["top"][i]),
            "width": int(data["width"][i]),
            "height": int(data["height"][i]),
            "line": (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i])),
        })
    return words


@lru_cache(maxsize=1)
def _easyocr_reader(langs: tuple[str, ...]):
    import easyocr  # heavy (torch); only imported when the easyocr backend runs

    return easyocr.Reader(list(langs), gpu=False)


def _load_words_easyocr(image_path: str, langs: tuple[str, ...] = ("en",)) -> list[dict[str, Any]]:
    """EasyOCR returns line-level detections; split each into words that share
    the line's box and confidence so the phrase-window matcher works unchanged.
    """
    try:
        _easyocr_reader(langs)
    except ImportError as exc:
        raise RuntimeError(
            "OCR_BACKEND='easyocr' but easyocr is not installed — "
            "`pip install easyocr` (pulls in torch), or set OCR_BACKEND='tesseract'."
        ) from exc

    reader = _easyocr_reader(langs)
    words: list[dict[str, Any]] = []
    for line_idx, (box, text, conf) in enumerate(reader.readtext(image_path)):
        if not text or not text.strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        left, top, right, bottom = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        for tok in text.split():
            words.append({
                "text": tok,
                "norm": _normalise(tok),
                "conf": float(conf),
                "left": left,
                "top": top,
                "width": right - left,
                "height": bottom - top,
                "line": (line_idx,),
            })
    return words


def _union_bounds(ws: list[dict[str, Any]]) -> dict[str, int]:
    left = min(w["left"] for w in ws)
    top = min(w["top"] for w in ws)
    right = max(w["left"] + w["width"] for w in ws)
    bottom = max(w["top"] + w["height"] for w in ws)
    return {"left": left, "top": top, "right": right, "bottom": bottom,
            "center": ((left + right) // 2, (top + bottom) // 2)}


def ocr_find(image_path: str, text: str) -> list[dict[str, Any]]:
    """Find every occurrence of ``text`` in the screenshot.

    Returns a list of ``{text, confidence, bounds}`` (bounds includes a
    ``center`` tuple), best confidence first. Empty list when nothing matches.
    """
    target = _tokens(text)
    if not target:
        return []
    words = _load_words(image_path)

    # group words by line, preserving order
    lines: dict[tuple, list[dict[str, Any]]] = {}
    for w in words:
        lines.setdefault(w["line"], []).append(w)

    matches: list[dict[str, Any]] = []
    span = len(target)
    for line_words in lines.values():
        norms = [w["norm"] for w in line_words]
        if span == 1:
            # single token: exact word, or token contained in a word
            for w in line_words:
                if w["norm"] == target[0] or target[0] in w["norm"]:
                    b = _union_bounds([w])
                    matches.append({"text": w["text"], "confidence": w["conf"], "bounds": b})
        else:
            for start in range(0, len(line_words) - span + 1):
                window = line_words[start:start + span]
                if [x["norm"] for x in window] == target:
                    b = _union_bounds(window)
                    conf = sum(x["conf"] for x in window) / span
                    matches.append({
                        "text": " ".join(x["text"] for x in window),
                        "confidence": conf, "bounds": b,
                    })

    matches.sort(key=lambda m: m["confidence"], reverse=True)
    return matches


def ocr_text_exists(image_path: str, text: str,
                    min_confidence: float = OCR_MIN_CONFIDENCE) -> tuple[bool, float]:
    """Does ``text`` appear on screen with sufficient confidence?

    Returns ``(found, best_confidence)``. ``found`` is True only when the best
    match meets ``min_confidence``.
    """
    matches = ocr_find(image_path, text)
    if not matches:
        return False, 0.0
    best = matches[0]["confidence"]
    return best >= min_confidence, best


def best_match(image_path: str, text: str) -> Optional[dict[str, Any]]:
    """Highest-confidence match for ``text``, or None."""
    matches = ocr_find(image_path, text)
    return matches[0] if matches else None
