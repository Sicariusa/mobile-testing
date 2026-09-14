"""Central configuration — every tunable threshold and bound lives here.

Keeping these in one place is deliberate: the executor and validator must stay
deterministic, so the only knobs that change their behaviour are gathered here
where they are easy to find and tune. No other module should hard-code a
threshold or timeout.
"""
from __future__ import annotations

# --- OCR ---------------------------------------------------------------------
# Minimum confidence (0..1) for an OCR match to count as a real hit. Tesseract
# reports 0..100; ocr.py normalises to 0..1 before comparing.
OCR_MIN_CONFIDENCE: float = 0.60

# OCR engine: "tesseract" (default, no extra deps) or "easyocr" (optional, more
# robust on stylised text; `pip install easyocr`, pulls in torch). ocr.py loads
# the chosen backend lazily, so importing it never requires the optional one.
OCR_BACKEND: str = "tesseract"

# --- Change detection --------------------------------------------------------
# A "screen_changed" assertion passes when the before/after difference ratio
# (hierarchy diff OR screenshot pixel diff, whichever is larger) meets this.
# Range 0..1. This is EVIDENCE OF A STATE TRANSITION, never semantic proof of
# any other assertion — see validator.py.
CHANGE_MIN: float = 0.02

# --- Stabilisation (settle) --------------------------------------------------
SETTLE_TIMEOUT_S: float = 5.0        # give up waiting for a stable screen after this
SETTLE_POLL_INTERVAL_S: float = 0.3  # gap between the two hierarchy dumps we compare
# Optional stronger settle: also require two screenshots to be pixel-stable
# (animation/frame idle), not just the hierarchy. Off by default — it costs two
# extra captures per settle. SCREEN_EPSILON is the max change_ratio still "idle".
SETTLE_REQUIRE_SCREEN_STABLE: bool = False
SETTLE_SCREEN_EPSILON: float = 0.02

# --- Performance -------------------------------------------------------------
# Memoize the live hierarchy dump within one screen state: consumers that read
# the screen back-to-back (resolve, recovery's no-progress check) reuse one dump
# instead of each issuing a slow adb uiautomator dump. Any mutating action (tap,
# type, scroll, back, launch) invalidates it. `settle` bypasses the memo because
# it exists to detect change.
HIERARCHY_CACHE: bool = True

# --- Recovery bounds ---------------------------------------------------------
RECOVERY_MAX_RETRIES: int = 3        # wait/retry attempts before escalating
RECOVERY_RETRY_WAIT_S: float = 0.8   # wait between retries
RECOVERY_MAX_SCROLLS: int = 3        # scroll-into-view attempts

# --- Resolver ----------------------------------------------------------------
RESOLVER_MAX_SCROLLS: int = 3        # find_with_scroll bound
# Inventory candidate ranking (label → element auto-binding, engine/resolver.py):
RESOLVE_MIN_SCORE: float = 0.60      # min candidate score to accept a ranked match
RESOLVE_AMBIGUOUS_GAP: float = 0.10  # top two within this margin => AMBIGUOUS

# --- Evidence / report -------------------------------------------------------
THUMBNAIL_MAX_WIDTH: int = 320       # px width of before/after thumbnails in the report

# --- Crash detection ---------------------------------------------------------
# Substrings in logcat that mark a fatal app crash since launch.
FATAL_LOGCAT_MARKERS: tuple[str, ...] = (
    "FATAL EXCEPTION",
    "ANR in ",
    "signal 11 (SIGSEGV)",
)
