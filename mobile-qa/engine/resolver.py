"""Resolver — turn a target selector object into a concrete location.

Priority (highest first), matching the brief:

    id  ->  text (exact, then contains)  ->  desc  ->  ocr

The first four are hierarchy selectors (confidence 1.0). ``ocr`` is a genuine
*fallback*, used only when selectors cannot reach the target: it finds the label
on the screenshot and returns tap coordinates with the OCR confidence. Every
attempt is recorded on the ResolutionResult so a report can later say
"resolved through OCR after hierarchy selectors failed".
"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

from . import models
from .config import OCR_MIN_CONFIDENCE, RESOLVER_MAX_SCROLLS
from .device import Device
from .models import ResolutionResult
from . import ocr as ocr_mod


def _selector_plan(target: dict[str, Any]) -> list[tuple[str, str]]:
    """Ordered (strategy, value) hierarchy-selector attempts for this target."""
    plan: list[tuple[str, str]] = []
    if target.get("id"):
        plan.append((models.STRATEGY_RESOURCE_ID, target["id"]))
    if target.get("text"):
        plan.append((models.STRATEGY_TEXT_EXACT, target["text"]))
        plan.append((models.STRATEGY_TEXT_CONTAINS, target["text"]))
    if target.get("desc"):
        plan.append((models.STRATEGY_DESC, target["desc"]))
    return plan


def _ocr_query(target: dict[str, Any]) -> Optional[str]:
    """Text to look for via OCR when selectors fail: explicit ``ocr:`` wins,
    otherwise fall back to the target's ``text``."""
    return target.get("ocr") or target.get("text")


def resolve(d: Device, target: dict[str, Any], *,
            allow_ocr: bool = True,
            screenshot_path: Optional[str] = None) -> ResolutionResult:
    """Locate ``target`` on the *current* screen (no scrolling, no waiting).

    Selectors first; then, if ``allow_ocr`` and a query text is available, OCR
    the screenshot and return coordinates. Records every attempt.
    """
    result = ResolutionResult()

    for kind, value in _selector_plan(target):
        try:
            element = d.find(kind, value)
        except Exception as exc:
            result.record(kind, "error", value=value, error=str(exc))
            continue
        if element is not None:
            result.element = element
            result.strategy = kind
            result.confidence = 1.0
            result.record(kind, "hit", value=value)
            return result
        result.record(kind, "miss", value=value)

    if allow_ocr:
        query = _ocr_query(target)
        if query:
            match, shot = _ocr_locate(d, query, screenshot_path)
            if match and match["confidence"] >= OCR_MIN_CONFIDENCE:
                cx, cy = match["bounds"]["center"]
                result.coordinates = (cx, cy)
                result.strategy = models.STRATEGY_OCR
                result.confidence = match["confidence"]
                result.record(models.STRATEGY_OCR, "hit", value=query,
                              confidence=round(match["confidence"], 4))
                return result
            result.record(models.STRATEGY_OCR, "miss", value=query,
                          confidence=round(match["confidence"], 4) if match else 0.0)

    return result  # not found (result.found is False)


def find_with_scroll(d: Device, target: dict[str, Any],
                     max_scrolls: int = RESOLVER_MAX_SCROLLS) -> ResolutionResult:
    """Resolve, scrolling forward up to ``max_scrolls`` times to bring an
    off-screen target into view. Selector-only per pass (OCR handled by the
    caller/recovery as the final stage)."""
    result = resolve(d, target, allow_ocr=False)
    if result.found:
        return result
    for i in range(max_scrolls):
        try:
            d.scroll_forward()
        except Exception as exc:
            result.record("scroll", "error", detail=str(exc))
            break
        result.record("scroll", "forward", value=str(i + 1))
        step = resolve(d, target, allow_ocr=False)
        result.attempts.extend(step.attempts)
        if step.found:
            step.attempts = result.attempts
            return step
    return result


def _ocr_locate(d: Device, query: str,
                screenshot_path: Optional[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Capture a screenshot if needed and return the best OCR match for query."""
    own_temp = False
    path = screenshot_path
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="resolve_")
        os.close(fd)
        own_temp = True
    try:
        d.screenshot(path)
    except Exception:
        if own_temp and os.path.exists(path):
            os.unlink(path)
        return None, None
    try:
        match = ocr_mod.best_match(path, query)
    except Exception:
        match = None
    if own_temp and os.path.exists(path):
        os.unlink(path)
    return match, path
