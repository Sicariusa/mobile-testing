"""ScreenLibrary — a reusable map of the screens a user chose to test.

Captured up front by driving the app (``cli.py inspect --into-library``), one
record per screen. At run time the engine matches the current screen to a record
by its ``structural_fingerprint`` and resolves from the stored inventory, so most
live hierarchy dumps disappear and an off-screen target can be reached
deliberately (its captured bounds say which way to scroll).

Each record has an **immutable id** — identity is the id, never the label. The
label is human-facing only, so it may be edited or duplicated freely; remove and
rename operate on the id. Records reuse the exact element bundle shape
``cli.py inspect`` writes, so the inspector remains the single writer of a
screen's inventory. A ``structural_fingerprint`` is *evidence of a possible
duplicate*, never proof a capture is invalid: two structurally different states
can share an element count yet mean different things.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from . import inspect as inspect_mod


def _new_id() -> str:
    return "scr_" + uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ScreenLibrary:
    def __init__(self, package: str, base_dir: str = "screens"):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", package or "app")
        self.package = package
        self.dir = os.path.join(base_dir, safe)
        self.path = os.path.join(self.dir, "library.json")
        self.data: dict[str, Any] = {"package": package, "screens": []}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict) and isinstance(loaded.get("screens"), list):
                self.data = loaded
        except (OSError, ValueError):
            pass
        if self._migrate():
            self.save()

    # -- migration -----------------------------------------------------------
    def _migrate(self) -> bool:
        """Backfill an immutable id (and best-effort metadata) onto any legacy
        record captured before ids existed. Returns True if anything changed."""
        changed = False
        for rec in self.data.get("screens", []):
            if not rec.get("id"):
                rec["id"] = _new_id()
                changed = True
            if "package" not in rec:
                rec["package"] = self.package
                changed = True
            if "captured_at" not in rec:
                rec["captured_at"] = ""
                changed = True
            if "is_checkpoint" not in rec:
                rec["is_checkpoint"] = False
                changed = True
        return changed

    # -- capture -------------------------------------------------------------
    def add(self, observation, label: str, *,
            screenshot: Optional[str] = None,
            checkpoint: bool = False) -> dict[str, Any]:
        """Capture ``observation`` as the screen ``label``.

        Re-capturing an existing label updates that record **in place, keeping
        its id** (so a re-capture to fix a bad grab keeps a stable handle);
        otherwise a new record with a fresh id is created. ``checkpoint`` marks
        the screen as a crawl **starting point** (the anchor a crawl runs from).
        """
        existing = next((s for s in self.screens() if s.get("label") == label), None)
        record = {
            "id": existing["id"] if existing else _new_id(),
            "label": label,
            "package": observation.package or self.package,
            "activity": observation.activity,
            "structural_fingerprint": observation.structural_fingerprint(),
            "content_fingerprint": observation.content_fingerprint(),
            "screenshot": screenshot,
            "captured_at": _now(),
            "is_checkpoint": bool(checkpoint) or bool(existing and existing.get("is_checkpoint")),
            "elements": [e.as_dict() for e in observation.elements()],
        }
        self.data["screens"] = [s for s in self.screens()
                                if s.get("id") != record["id"]]
        self.data["screens"].append(record)
        return record

    # -- edit ----------------------------------------------------------------
    def get(self, screen_id: str) -> Optional[dict[str, Any]]:
        return next((s for s in self.screens() if s.get("id") == screen_id), None)

    def remove(self, screen_id: str) -> bool:
        """Remove the record with this id. Returns True if one was removed."""
        before = len(self.screens())
        self.data["screens"] = [s for s in self.screens()
                                if s.get("id") != screen_id]
        return len(self.data["screens"]) < before

    def rename(self, screen_id: str, new_label: str) -> bool:
        """Relabel a record (id and capture unchanged). Duplicate labels are
        allowed — the tester owns the naming. Returns True if the id existed."""
        rec = self.get(screen_id)
        if rec is None:
            return False
        rec["label"] = new_label
        return True

    def set_checkpoint(self, screen_id: str, value: bool = True) -> bool:
        """Flag (or unflag) a record as a crawl starting point. Returns True if
        the id existed."""
        rec = self.get(screen_id)
        if rec is None:
            return False
        rec["is_checkpoint"] = bool(value)
        return True

    # -- read ----------------------------------------------------------------
    def screens(self) -> list[dict[str, Any]]:
        return self.data.get("screens", [])

    def match(self, fingerprint: str) -> Optional[dict[str, Any]]:
        """The captured record whose structural fingerprint equals ``fingerprint``
        (the same-structure test used by the selector cache), or None."""
        if not fingerprint:
            return None
        for record in self.screens():
            if record.get("structural_fingerprint") == fingerprint:
                return record
        return None

    def duplicates(self) -> dict[str, list[str]]:
        """Map a structural fingerprint to the ids sharing it, for fingerprints
        held by more than one record — a *hint*, not a validity judgement."""
        by_fp: dict[str, list[str]] = {}
        for rec in self.screens():
            fp = rec.get("structural_fingerprint") or ""
            by_fp.setdefault(fp, []).append(rec.get("id"))
        return {fp: ids for fp, ids in by_fp.items() if fp and len(ids) > 1}

    def elements(self, record: dict[str, Any]) -> list[inspect_mod.Element]:
        """Rebuild :class:`Element`s from a stored record for ranking/offsets."""
        return [_element_from_dict(d) for d in record.get("elements", [])]

    def find_bearing(self, query: str, role: str = "tappable") -> Optional[dict[str, Any]]:
        """Across *all* captured screens, the best element matching ``query`` and
        its captured center — a hint for where an off-screen target lives so
        recovery can scroll toward it instead of blindly."""
        best = None
        for record in self.screens():
            els = self.elements(record)
            cands = inspect_mod.rank_candidates(query, els, role=role, limit=1)
            if cands and cands[0].base >= 0.60:
                c = cands[0]
                if best is None or c.base > best[0]:
                    best = (c.base, record, c.element.center())
        if best is None:
            return None
        _, record, center = best
        return {"id": record.get("id"), "label": record.get("label"), "center": center}

    def save(self) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass


def _element_from_dict(d: dict[str, Any]) -> inspect_mod.Element:
    """Reconstruct an Element from a stored ``as_dict`` (ignores derived keys)."""
    return inspect_mod.Element(
        resource_id=d.get("resource_id", ""),
        text=d.get("text", ""),
        content_desc=d.get("content_desc", ""),
        cls=d.get("cls", ""),
        clickable=bool(d.get("clickable")),
        long_clickable=bool(d.get("long_clickable")),
        checkable=bool(d.get("checkable")),
        editable=bool(d.get("editable")),
        password=bool(d.get("password")),
        focused=bool(d.get("focused")),
        enabled=bool(d.get("enabled", True)),
        selected=bool(d.get("selected")),
        bounds=d.get("bounds") or {"center": (0, 0)},
        index=int(d.get("index", 0) or 0),
        depth=int(d.get("depth", 0) or 0),
        parent_index=int(d.get("parent_index", -1)),
    )
