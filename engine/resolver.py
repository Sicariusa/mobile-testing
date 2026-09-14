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

from . import inspect as inspect_mod
from . import models
from .config import (OCR_MIN_CONFIDENCE, RESOLVE_AMBIGUOUS_GAP, RESOLVE_MIN_SCORE,
                     RESOLVER_MAX_SCROLLS)
from .device import Device
from .models import ResolutionResult
from . import ocr as ocr_mod


def _query_text(target: dict[str, Any]) -> str:
    """The human label to rank/OCR by: explicit label/text/desc, else the id tail."""
    if target.get("label"):
        return str(target["label"]).strip()
    if target.get("text"):
        return str(target["text"]).strip()
    if target.get("desc"):
        return str(target["desc"]).strip()
    if target.get("id"):
        return str(target["id"]).rsplit("/", 1)[-1]
    return ""


def _role_ok(el, role: str) -> bool:
    """A ranked match must fit the action's role: a field must be editable, a
    tap target must be clickable. This stops a non-clickable label (e.g. a
    'Sign in' heading) from being tapped instead of the real button."""
    if role == "field":
        return el.editable
    if role == "tappable":
        return el.clickable
    return True


def _concrete_selector(el) -> Optional[dict[str, Any]]:
    """A cacheable, re-findable selector for a ranked element (id > text > desc)."""
    if el.resource_id:
        return {"strategy": models.STRATEGY_RESOURCE_ID, "value": el.resource_id}
    if el.text.strip():
        return {"strategy": models.STRATEGY_TEXT_EXACT, "value": el.text.strip()}
    if el.content_desc.strip():
        return {"strategy": models.STRATEGY_DESC, "value": el.content_desc.strip()}
    return None


def _screen(d: Device) -> tuple[str, list]:
    """Current structural fingerprint + parsed elements (empty on any failure)."""
    try:
        els = inspect_mod.parse_elements(d.dump_hierarchy())
        return inspect_mod.structural_fingerprint(d.current_activity(), els), els
    except Exception:
        return "", []


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
            screenshot_path: Optional[str] = None,
            role: str = "tappable",
            cache=None) -> ResolutionResult:
    """Locate ``target`` on the *current* screen (no scrolling, no waiting).

    Order: explicit selectors (EXACT) → cache fast-path → inventory candidate
    ranking (label→element, MATCHED/AMBIGUOUS) → OCR. ``role`` (``field`` |
    ``tappable``) biases ranking; ``cache`` (a SelectorCache) learns and reuses
    concrete bindings per screen. Records every attempt.
    """
    result = ResolutionResult()

    # 1. explicit selectors — a direct hit is EXACT
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
            result.status = models.RESOLVE_EXACT
            result.record(kind, "hit", value=value)
            return result
        result.record(kind, "miss", value=value)

    query = _query_text(target)
    fingerprint, elements = _screen(d) if (cache is not None or query) else ("", [])

    # 2. cache fast-path (self-healing: a stale binding just falls through)
    if cache is not None and query and fingerprint:
        sel = cache.get(fingerprint, role, query)
        if sel and sel.get("strategy"):
            try:
                el = d.find(sel["strategy"], sel["value"])
            except Exception:
                el = None
            if el is not None:
                result.element = el
                result.strategy = sel["strategy"]
                result.confidence = 1.0
                result.status = models.RESOLVE_MATCHED
                result.bound_selector = sel
                result.record("cache", "hit", value=sel.get("value"))
                return result
            result.record("cache", "stale", value=sel.get("value"))

    # 3. inventory candidate ranking (label → element)
    if query and elements:
        cands = inspect_mod.rank_candidates(query, elements, role=role)
        result.candidates = [c.as_dict() for c in cands]
        # accept on base text similarity AND role fitness — role bonuses only
        # order candidates; a strong text match on a wrong-role element is skipped.
        acceptable = [c for c in cands
                      if c.base >= RESOLVE_MIN_SCORE and _role_ok(c.element, role)]
        if acceptable:
            top = acceptable[0]
            ambiguous = (len(acceptable) > 1 and acceptable[1].base >= RESOLVE_MIN_SCORE
                         and (top.base - acceptable[1].base) < RESOLVE_AMBIGUOUS_GAP)
            sel = _concrete_selector(top.element)
            bound = None
            if sel:
                try:
                    bound = d.find(sel["strategy"], sel["value"])
                except Exception:
                    bound = None
            if bound is not None:
                result.element = bound
            else:
                result.coordinates = top.element.center()
                sel = {"coordinates": list(top.element.center())}
            result.strategy = models.STRATEGY_RANKED
            result.confidence = top.score
            result.status = (models.RESOLVE_AMBIGUOUS if ambiguous
                             else models.RESOLVE_MATCHED)
            result.reasons = top.reasons
            result.bound_selector = sel
            if cache is not None and fingerprint and sel.get("strategy"):
                cache.put(fingerprint, role, query, sel)
            result.record("ranked", "hit", value=query, confidence=round(top.score, 3))
            return result

    # 4. OCR fallback
    if allow_ocr:
        oq = _ocr_query(target)
        if oq:
            match, shot = _ocr_locate(d, oq, screenshot_path)
            if match and match["confidence"] >= OCR_MIN_CONFIDENCE:
                cx, cy = match["bounds"]["center"]
                result.coordinates = (cx, cy)
                result.strategy = models.STRATEGY_OCR
                result.confidence = match["confidence"]
                result.status = models.RESOLVE_MATCHED
                result.record(models.STRATEGY_OCR, "hit", value=oq,
                              confidence=round(match["confidence"], 4))
                return result
            result.record(models.STRATEGY_OCR, "miss", value=oq,
                          confidence=round(match["confidence"], 4) if match else 0.0)

    if result.status is None:
        result.status = models.RESOLVE_NOT_FOUND
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
