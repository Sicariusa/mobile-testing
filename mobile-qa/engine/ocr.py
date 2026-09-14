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
from typing import Any, Optional

from .config import OCR_MIN_CONFIDENCE


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _tokens(s: str) -> list[str]:
    return _normalise(s).split()


def _load_words(image_path: str) -> list[dict[str, Any]]:
    """Return per-word OCR entries with normalised text, confidence 0..1, bounds
    and a stable line id. Import-lazy so the module imports without Tesseract.
    """
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
