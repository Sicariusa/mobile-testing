"""Shared data models — the common language of the whole engine.

Every module communicates through these four dataclasses instead of inventing
its own dict/tuple return shape:

    Observation        a concrete point in time (what the screen was)
    ResolutionResult   how a target was located (or not)
    RecoveryTrace      the ordered story of reaching a stubborn target
    ActionResult       the full outcome of one step, with reasoning metadata

They all serialise to plain JSON via ``as_dict()`` so they can be written into
``timeline.json`` and rendered by the HTML report without any per-module glue.
Keeping ``resolved_by``/``validated_by`` (and their confidences) as first-class
fields is intentional: *how* a result was reached is one of the most valuable
outputs of a QA engine, not an incidental detail.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class Status(str, Enum):
    """Outcome of a single step. ``str`` mixin => serialises as its value."""

    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"   # target unreachable even after recovery
    CRASH = "CRASH"       # app died (fatal in logcat)
    SKIPPED = "SKIPPED"   # a prior fatal step aborted the run


# --- selector / validation strategy names (used across modules) --------------
STRATEGY_RESOURCE_ID = "resource_id"
STRATEGY_TEXT_EXACT = "text_exact"
STRATEGY_TEXT_CONTAINS = "text_contains"
STRATEGY_DESC = "desc"
STRATEGY_OCR = "ocr"

VALIDATED_HIERARCHY = "hierarchy"
VALIDATED_OCR = "ocr"
VALIDATED_CHANGE = "change"


class FailureReason:
    """Why a step could not complete — a precise alternative to a bare BLOCKED."""

    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    TARGET_DISABLED = "TARGET_DISABLED"
    TARGET_NOT_CLICKABLE = "TARGET_NOT_CLICKABLE"
    UNEXPECTED_SCREEN = "UNEXPECTED_SCREEN"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    DEVICE_ERROR = "DEVICE_ERROR"
    APP_CRASHED = "APP_CRASHED"
    TIMEOUT = "TIMEOUT"


@dataclass
class Observation:
    """A concrete snapshot of the device at one instant.

    Two Observations (before/after a step) are the substrate the validator and,
    later, an autonomous agent reason over. ``transition`` derives the deltas
    between them without touching the device.
    """

    timestamp: float
    package: Optional[str] = None
    activity: Optional[str] = None
    screenshot_path: Optional[str] = None
    hierarchy_xml: Optional[str] = None
    keyboard_visible: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    # -- derived text (cached lazily; not part of the serialised record) ------
    def texts(self) -> set[str]:
        """All non-empty ``text``/``content-desc`` values in the hierarchy."""
        return _hierarchy_texts(self.hierarchy_xml)

    # -- richer perception (lazy; inspect imported here to avoid a cycle) ------
    def elements(self) -> list[Any]:
        """Parsed accessibility-tree elements (cached per instance)."""
        cached = getattr(self, "_elements_cache", None)
        if cached is None:
            from . import inspect as inspect_mod
            cached = inspect_mod.parse_elements(self.hierarchy_xml)
            self._elements_cache = cached
        return cached

    def structural_fingerprint(self) -> str:
        from . import inspect as inspect_mod
        return inspect_mod.structural_fingerprint(self.activity, self.elements())

    def content_fingerprint(self) -> str:
        from . import inspect as inspect_mod
        return inspect_mod.content_fingerprint(self.activity, self.elements())

    def window(self) -> dict[str, bool]:
        """Overlay/keyboard flags for this screen (dialog detection + keyboard)."""
        from . import inspect as inspect_mod
        flags = inspect_mod.window_flags(self.elements())
        flags["keyboard"] = self.keyboard_visible
        return flags

    @staticmethod
    def transition(before: "Observation", after: "Observation") -> dict[str, Any]:
        """Pure diff between two observations — the basis for change detection
        and future state-transition reasoning. No device access."""
        before_texts = before.texts()
        after_texts = after.texts()
        return {
            "activity_changed": before.activity != after.activity,
            "hierarchy_changed": (before.hierarchy_xml or "") != (after.hierarchy_xml or ""),
            "keyboard_changed": before.keyboard_visible != after.keyboard_visible,
            "new_text": sorted(after_texts - before_texts),
            "removed_text": sorted(before_texts - after_texts),
        }


@dataclass
class ResolutionResult:
    """How (and whether) a target was located on the current screen.

    Exactly one of ``element`` / ``coordinates`` is set on success:
      * selector hit -> ``element`` (a device handle), ``confidence`` 1.0
      * OCR fallback -> ``coordinates`` (tap center), ``confidence`` = OCR score
    ``element`` is deliberately excluded from ``as_dict`` (not serialisable).
    """

    element: Any = None                       # opaque device handle, or None
    coordinates: Optional[tuple[int, int]] = None
    strategy: Optional[str] = None            # resource_id | text_* | desc | ocr
    confidence: float = 0.0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.element is not None or self.coordinates is not None

    def record(self, method: str, outcome: str, **detail: Any) -> None:
        entry = {"method": method, "outcome": outcome}
        entry.update(detail)
        self.attempts.append(entry)

    def as_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "strategy": self.strategy,
            "confidence": round(self.confidence, 4),
            "coordinates": list(self.coordinates) if self.coordinates else None,
            "resolved_via_element": self.element is not None,
            "attempts": self.attempts,
        }


@dataclass
class RecoveryTrace:
    """Ordered story of trying to reach a target (wait, keyboard, scroll, OCR)."""

    attempts: list[dict[str, Any]] = field(default_factory=list)

    def record(self, method: str, outcome: str, detail: str = "") -> None:
        self.attempts.append({"method": method, "outcome": outcome, "detail": detail})

    def as_dict(self) -> dict[str, Any]:
        return {"attempts": self.attempts}


@dataclass
class ActionResult:
    """The full, self-describing outcome of one step.

    The reasoning metadata (``resolved_by``, ``validated_by`` and their
    confidences, ``recovery``, ``crash_signature``) is treated as a primary
    output — it is what makes a report worth reading.
    """

    status: Status
    action: str                                   # tap | type | swipe | launch | assert:<type>
    target: Optional[dict[str, Any]] = None
    value: Optional[str] = None
    resolved_by: Optional[str] = None             # strategy name, or None
    resolved_confidence: Optional[float] = None
    validated_by: Optional[str] = None            # hierarchy | ocr | change | None
    validation_confidence: Optional[float] = None
    duration_ms: int = 0
    recovery: RecoveryTrace = field(default_factory=RecoveryTrace)
    ocr_matches: list[dict[str, Any]] = field(default_factory=list)
    before: Optional[Observation] = None
    after: Optional[Observation] = None
    detail: str = ""
    error: str = ""
    crash_signature: str = ""
    # diagnostics on failure — precise reason + on-screen candidates + diff
    failure_reason: Optional[str] = None
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    screen_summary: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value if isinstance(self.status, Status) else self.status,
            "action": self.action,
            "target": self.target,
            "value": self.value,
            "resolved_by": self.resolved_by,
            "resolved_confidence": (
                round(self.resolved_confidence, 4)
                if self.resolved_confidence is not None else None
            ),
            "validated_by": self.validated_by,
            "validation_confidence": (
                round(self.validation_confidence, 4)
                if self.validation_confidence is not None else None
            ),
            "duration_ms": self.duration_ms,
            "recovery": self.recovery.as_dict(),
            "ocr_matches": self.ocr_matches,
            "before": self.before.as_dict() if self.before else None,
            "after": self.after.as_dict() if self.after else None,
            "detail": self.detail,
            "error": self.error,
            "crash_signature": self.crash_signature,
            "failure_reason": self.failure_reason,
            "suggestions": self.suggestions,
            "screen_summary": self.screen_summary,
        }


# --- helpers -----------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


def _hierarchy_texts(hierarchy_xml: Optional[str]) -> set[str]:
    """Extract every ``text`` and ``content-desc`` value from a uiautomator dump.

    Tolerant of ``None``/malformed XML (returns an empty set) so callers never
    have to guard it.
    """
    if not hierarchy_xml:
        return set()
    out: set[str] = set()
    try:
        root = ET.fromstring(hierarchy_xml)
    except ET.ParseError:
        return out
    for node in root.iter():
        for attr in ("text", "content-desc"):
            val = node.get(attr)
            if val and val.strip():
                out.add(val.strip())
    return out
