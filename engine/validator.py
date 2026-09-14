"""Validator — decide whether an expected outcome actually materialised.

Deterministic and fixed-order. The crash gate always runs first. After that the
logic is **per assertion type** — change detection is NOT a generic fallback
that can turn any assertion green:

    text_exists      hierarchy -> OCR -> FAIL
    ocr_text_exists  OCR -> FAIL
    element_exists   hierarchy -> FAIL
    activity_is      activity match -> FAIL
    screen_changed   change_ratio >= CHANGE_MIN -> PASS/FAIL

``screen_changed`` is the *only* assertion validated by change detection, and
its meaning is explicit: **evidence that a state transition occurred, never
semantic proof that some other expectation was met.** (Tapping Login and
landing on an error screen changes the screen but is not a successful login.)
"""
from __future__ import annotations

import difflib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Optional

from . import models
from .config import CHANGE_MIN, FATAL_LOGCAT_MARKERS, OCR_MIN_CONFIDENCE
from .models import Observation, Status
from . import ocr as ocr_mod


@dataclass
class ValidationOutcome:
    status: Status
    validated_by: Optional[str] = None       # hierarchy | ocr | change | None
    confidence: Optional[float] = None
    detail: str = ""
    crash_signature: str = ""


def logcat_fatal(logcat_text: str) -> Optional[str]:
    """Return the first fatal line found in logcat, or None."""
    if not logcat_text:
        return None
    for line in logcat_text.splitlines():
        for marker in FATAL_LOGCAT_MARKERS:
            if marker in line:
                return line.strip()
    return None


def change_ratio(before: Observation, after: Observation) -> float:
    """Difference between two observations in [0, 1] — max of hierarchy diff and
    screenshot pixel diff (whichever signals are available)."""
    signals = [_hierarchy_diff(before.hierarchy_xml, after.hierarchy_xml)]
    pix = _screenshot_diff(before.screenshot_path, after.screenshot_path)
    if pix is not None:
        signals.append(pix)
    return max(signals)


def validate(assertion: dict[str, Any], before: Observation, after: Observation,
             logcat: str = "") -> ValidationOutcome:
    """Run the fixed-order algorithm for one assertion."""
    # 1. crash gate — always first
    fatal = logcat_fatal(logcat)
    if fatal:
        return ValidationOutcome(Status.CRASH, None, None,
                                 detail="fatal detected in logcat", crash_signature=fatal)

    kind = assertion.get("type")
    expected = assertion.get("value")

    if kind == "text_exists":
        # hierarchy first (fast, exact), then OCR (visual text the tree missed)
        if _hierarchy_has_text(after.hierarchy_xml, expected):
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"'{expected}' in hierarchy")
        found, conf = _ocr(after, expected)
        if found:
            return ValidationOutcome(Status.PASS, models.VALIDATED_OCR, conf,
                                     detail=f"'{expected}' via OCR")
        return ValidationOutcome(Status.FAIL, None, conf,
                                 detail=f"'{expected}' not in hierarchy or OCR")

    if kind == "ocr_text_exists":
        found, conf = _ocr(after, expected)
        if found:
            return ValidationOutcome(Status.PASS, models.VALIDATED_OCR, conf,
                                     detail=f"'{expected}' via OCR")
        return ValidationOutcome(Status.FAIL, None, conf,
                                 detail=f"'{expected}' not visible (OCR)")

    if kind == "element_exists":
        if _hierarchy_has_element(after.hierarchy_xml, assertion):
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail="element present in hierarchy")
        return ValidationOutcome(Status.FAIL, None, None, detail="element absent")

    if kind == "activity_is":
        if _activity_matches(after.activity, expected):
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"activity == {after.activity}")
        return ValidationOutcome(Status.FAIL, None, None,
                                 detail=f"activity {after.activity} != {expected}")

    if kind == "screen_changed":
        ratio = change_ratio(before, after)
        if ratio >= CHANGE_MIN:
            return ValidationOutcome(Status.PASS, models.VALIDATED_CHANGE, ratio,
                                     detail=f"change ratio {ratio:.3f} >= {CHANGE_MIN}")
        return ValidationOutcome(Status.FAIL, models.VALIDATED_CHANGE, ratio,
                                 detail=f"change ratio {ratio:.3f} < {CHANGE_MIN}")

    if kind == "not_visible":
        # inverse of text_exists — the string must be gone from tree AND screen
        if _hierarchy_has_text(after.hierarchy_xml, expected):
            return ValidationOutcome(Status.FAIL, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"'{expected}' still in hierarchy")
        found, conf = _ocr(after, expected)
        if found:
            return ValidationOutcome(Status.FAIL, models.VALIDATED_OCR, conf,
                                     detail=f"'{expected}' still visible (OCR)")
        return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                 detail=f"'{expected}' not visible")

    if kind == "activity_changed":
        if before.activity != after.activity:
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"activity {before.activity} -> {after.activity}")
        return ValidationOutcome(Status.FAIL, None, None,
                                 detail=f"activity unchanged ({after.activity})")

    return ValidationOutcome(Status.FAIL, None, None,
                             detail=f"unknown assertion type: {kind}")


# --- hierarchy helpers -------------------------------------------------------
def _hierarchy_has_text(xml: Optional[str], expected: Optional[str]) -> bool:
    if not xml or not expected:
        return False
    want = expected.strip().lower()
    for text in Observation(timestamp=0, hierarchy_xml=xml).texts():
        if want in text.lower():
            return True
    return False


def _hierarchy_has_element(xml: Optional[str], target: dict[str, Any]) -> bool:
    if not xml:
        return False
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    want_id = target.get("id")
    want_text = target.get("text")
    want_desc = target.get("desc")
    for node in root.iter():
        if want_id and node.get("resource-id") == want_id:
            return True
        if want_text and node.get("text") == want_text:
            return True
        if want_desc and node.get("content-desc") == want_desc:
            return True
    return False


def _activity_matches(activity: Optional[str], expected: Optional[str]) -> bool:
    if not activity or not expected:
        return False
    return activity == expected or activity.endswith(expected) or expected in activity


# --- OCR + diff helpers ------------------------------------------------------
def _ocr(after: Observation, expected: Optional[str]) -> tuple[bool, float]:
    if not after.screenshot_path or not expected:
        return False, 0.0
    try:
        return ocr_mod.ocr_text_exists(after.screenshot_path, expected, OCR_MIN_CONFIDENCE)
    except Exception:
        return False, 0.0


def _hierarchy_diff(a: Optional[str], b: Optional[str]) -> float:
    a, b = a or "", b or ""
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def _screenshot_diff(a: Optional[str], b: Optional[str]) -> Optional[float]:
    if not a or not b:
        return None
    try:
        from PIL import Image, ImageChops
    except Exception:
        return None
    try:
        with Image.open(a) as ia, Image.open(b) as ib:
            ia = ia.convert("RGB")
            ib = ib.convert("RGB").resize(ia.size)
            diff = ImageChops.difference(ia, ib)
            hist = diff.histogram()
            # mean absolute channel difference, normalised to 0..1
            total = 0
            count = 0
            for ch in range(3):
                channel = hist[ch * 256:(ch + 1) * 256]
                total += sum(i * v for i, v in enumerate(channel))
                count += sum(channel)
            if count == 0:
                return 0.0
            return (total / count) / 255.0
    except Exception:
        return None
