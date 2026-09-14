"""ScreenLibrary — a reusable map of the screens a user chose to test.

Captured up front by driving the app (``cli.py inspect --into-library``), one
entry per screen keyed by its ``structural_fingerprint``. At run time the engine
matches the current screen to an entry and resolves from the stored inventory,
so most live hierarchy dumps disappear and an off-screen target can be reached
deliberately (its captured bounds say which way to scroll).

Entries reuse the exact bundle shape ``cli.py inspect`` already writes, so the
inspector remains the single writer of a screen's element inventory.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from . import inspect as inspect_mod


class ScreenLibrary:
    def __init__(self, package: str, base_dir: str = "screens"):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", package or "app")
        self.package = package
        self.path = os.path.join(base_dir, safe, "library.json")
        self.data: dict[str, Any] = {"package": package, "screens": []}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict) and isinstance(loaded.get("screens"), list):
                self.data = loaded
        except (OSError, ValueError):
            pass

    def add(self, observation, label: str, *, screenshot: Optional[str] = None) -> dict[str, Any]:
        """Capture ``observation`` as the screen ``label``. Re-capturing a label
        replaces its entry; a different label on the same fingerprint is allowed
        (the same screen may be tested under more than one name)."""
        entry = {
            "label": label,
            "activity": observation.activity,
            "structural_fingerprint": observation.structural_fingerprint(),
            "content_fingerprint": observation.content_fingerprint(),
            "screenshot": screenshot,
            "elements": [e.as_dict() for e in observation.elements()],
        }
        self.data["screens"] = [s for s in self.screens() if s.get("label") != label]
        self.data["screens"].append(entry)
        return entry

    def screens(self) -> list[dict[str, Any]]:
        return self.data.get("screens", [])

    def match(self, fingerprint: str) -> Optional[dict[str, Any]]:
        """The captured entry whose structural fingerprint equals ``fingerprint``
        (the same-structure test used by the selector cache), or None."""
        if not fingerprint:
            return None
        for entry in self.screens():
            if entry.get("structural_fingerprint") == fingerprint:
                return entry
        return None

    def elements(self, entry: dict[str, Any]) -> list[inspect_mod.Element]:
        """Rebuild :class:`Element`s from a stored entry for ranking/offsets."""
        return [_element_from_dict(d) for d in entry.get("elements", [])]

    def find_bearing(self, query: str, role: str = "tappable") -> Optional[dict[str, Any]]:
        """Across *all* captured screens, the best element matching ``query`` and
        its captured center — a hint for where an off-screen target lives so
        recovery can scroll toward it instead of blindly."""
        best = None
        for entry in self.screens():
            els = self.elements(entry)
            cands = inspect_mod.rank_candidates(query, els, role=role, limit=1)
            if cands and cands[0].base >= 0.60:
                c = cands[0]
                if best is None or c.base > best[0]:
                    best = (c.base, entry, c.element.center())
        if best is None:
            return None
        _, entry, center = best
        return {"label": entry.get("label"), "center": center}

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
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
