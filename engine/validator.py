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
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
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
    # structured evidence (does NOT influence the verdict — enrichment only)
    expected: Optional[str] = None
    actual: Optional[str] = None
    observed_texts: list = field(default_factory=list)


def _observed_texts(obs, expected: Optional[str], limit: int = 8) -> list:
    """On-screen texts as failure evidence, ordered by closeness to ``expected``
    for readability. Ordering only — it never decides pass/fail."""
    try:
        texts = [t for t in obs.texts() if t]
    except Exception:
        return []
    if expected:
        want = str(expected).strip().lower()
        texts.sort(key=lambda t: difflib.SequenceMatcher(None, want, t.lower()).ratio(),
                   reverse=True)
    return texts[:limit]


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
    match_mode = assertion.get("match") or "word"

    if kind == "text_exists":
        # hierarchy first (fast, exact), then OCR (visual text the tree missed)
        if _hierarchy_has_text(after.hierarchy_xml, expected, match_mode):
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"'{expected}' in hierarchy",
                                     expected=expected, actual=expected)
        found, conf = _ocr(after, expected)
        if found:
            return ValidationOutcome(Status.PASS, models.VALIDATED_OCR, conf,
                                     detail=f"'{expected}' via OCR",
                                     expected=expected, actual=expected)
        return ValidationOutcome(Status.FAIL, None, conf,
                                 detail=f"'{expected}' not in hierarchy or OCR",
                                 expected=expected, actual=None,
                                 observed_texts=_observed_texts(after, expected))

    if kind == "ocr_text_exists":
        found, conf = _ocr(after, expected)
        if found:
            return ValidationOutcome(Status.PASS, models.VALIDATED_OCR, conf,
                                     detail=f"'{expected}' via OCR",
                                     expected=expected, actual=expected)
        return ValidationOutcome(Status.FAIL, None, conf,
                                 detail=f"'{expected}' not visible (OCR)",
                                 expected=expected, actual=None,
                                 observed_texts=_observed_texts(after, expected))

    if kind == "element_exists":
        want = str(assertion.get("id") or assertion.get("text")
                   or assertion.get("desc") or expected or "element")
        if _hierarchy_has_element(after.hierarchy_xml, assertion):
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail="element present in hierarchy",
                                     expected=want, actual=want)
        return ValidationOutcome(Status.FAIL, None, None, detail="element absent",
                                 expected=want, actual=None,
                                 observed_texts=_observed_texts(after, want))

    if kind == "activity_is":
        if _activity_matches(after.activity, expected):
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"activity == {after.activity}",
                                     expected=expected, actual=after.activity)
        return ValidationOutcome(Status.FAIL, None, None,
                                 detail=f"activity {after.activity} != {expected}",
                                 expected=expected, actual=after.activity)

    if kind == "screen_changed":
        ratio = change_ratio(before, after)
        exp = f"screen change ≥ {CHANGE_MIN}"
        if ratio >= CHANGE_MIN:
            return ValidationOutcome(Status.PASS, models.VALIDATED_CHANGE, ratio,
                                     detail=f"change ratio {ratio:.3f} >= {CHANGE_MIN}",
                                     expected=exp, actual=f"ratio {ratio:.3f}")
        return ValidationOutcome(Status.FAIL, models.VALIDATED_CHANGE, ratio,
                                 detail=f"change ratio {ratio:.3f} < {CHANGE_MIN}",
                                 expected=exp, actual=f"ratio {ratio:.3f}")

    if kind == "not_visible":
        # inverse of text_exists — the string must be gone from tree AND screen
        exp = f"'{expected}' not visible"
        if _hierarchy_has_text(after.hierarchy_xml, expected, match_mode):
            return ValidationOutcome(Status.FAIL, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"'{expected}' still in hierarchy",
                                     expected=exp, actual=f"'{expected}' still visible",
                                     observed_texts=_observed_texts(after, expected))
        found, conf = _ocr(after, expected)
        if found:
            return ValidationOutcome(Status.FAIL, models.VALIDATED_OCR, conf,
                                     detail=f"'{expected}' still visible (OCR)",
                                     expected=exp, actual=f"'{expected}' still visible",
                                     observed_texts=_observed_texts(after, expected))
        return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                 detail=f"'{expected}' not visible",
                                 expected=exp, actual=exp)

    if kind == "activity_changed":
        exp = "activity change"
        if before.activity != after.activity:
            return ValidationOutcome(Status.PASS, models.VALIDATED_HIERARCHY, 1.0,
                                     detail=f"activity {before.activity} -> {after.activity}",
                                     expected=exp, actual=f"{before.activity} -> {after.activity}")
        return ValidationOutcome(Status.FAIL, None, None,
                                 detail=f"activity unchanged ({after.activity})",
                                 expected=exp, actual=f"unchanged ({after.activity})")

    return ValidationOutcome(Status.FAIL, None, None,
                             detail=f"unknown assertion type: {kind}")


# --- hierarchy helpers -------------------------------------------------------
def _text_matches(haystack: str, want: str, mode: str) -> bool:
    """Whether ``want`` is present in ``haystack`` under ``mode``.

    ``word`` (default) requires ``want`` to appear as a contiguous run of whole
    words, so 'ok' never matches inside 'Facebook' and 'Success' never matches
    'Unsuccessful'. ``exact`` requires the full normalised value to be equal;
    ``contains`` is the old raw-substring behaviour, opt-in only.
    """
    h = re.sub(r"\s+", " ", haystack or "").strip().lower()
    w = re.sub(r"\s+", " ", want or "").strip().lower()
    if not w:
        return False
    if mode == "contains":
        return w in h
    if mode == "exact":
        return h == w
    h_tokens = re.findall(r"\w+", h, flags=re.UNICODE)
    w_tokens = re.findall(r"\w+", w, flags=re.UNICODE)
    if not w_tokens:                       # want was pure punctuation
        return w in h
    span = len(w_tokens)
    return any(h_tokens[i:i + span] == w_tokens
               for i in range(0, len(h_tokens) - span + 1))


def _hierarchy_has_text(xml: Optional[str], expected: Optional[str],
                        mode: str = "word") -> bool:
    if not xml or not expected:
        return False
    for text in Observation(timestamp=0, hierarchy_xml=xml).texts():
        if _text_matches(text, str(expected), mode):
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
    if activity == expected:
        return True
    # suffix match only on a component boundary: '.HomeActivity' matches
    # 'com.app/.HomeActivity', but 'Cart' must not match 'ShoppingCartActivity'
    if activity.endswith(expected):
        prefix = activity[:-len(expected)]
        return not prefix or prefix[-1] in "./"
    return False


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
    if a == b:                       # settle's hot path: identical dumps -> no diff
        return 0.0
    if not a or not b:
        return 1.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=True)
    # SequenceMatcher.ratio() is O(len(a)*len(b)); on very large hierarchy dumps
    # fall back to quick_ratio() (O(n)) to bound worst-case cost.
    if len(a) + len(b) > 20000:
        return 1.0 - sm.quick_ratio()
    return 1.0 - sm.ratio()


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
