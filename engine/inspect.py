"""Perception helpers — turn one screen into a structured, queryable model.

This is the shared perception layer: :func:`parse_elements` reads a uiautomator
hierarchy into :class:`Element`s, :func:`screen_diff` compares two observations
into a :class:`ScreenDiff`, and :func:`rank_candidates` scores elements against a
human target (the deterministic seed of the future target resolver). It has no
dependency on the rest of the engine, so ``models.Observation`` can consume it
lazily without a cycle.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _as_bool(v: Optional[str]) -> bool:
    return v == "true"


def _parse_bounds(raw: Optional[str]) -> dict[str, Any]:
    m = _BOUNDS_RE.search(raw or "")
    if not m:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0, "center": (0, 0)}
    l, t, r, b = (int(x) for x in m.groups())
    return {"left": l, "top": t, "right": r, "bottom": b,
            "center": ((l + r) // 2, (t + b) // 2)}


@dataclass
class Element:
    """One node of the accessibility tree, with the attributes a locator needs."""

    resource_id: str = ""
    text: str = ""
    content_desc: str = ""
    cls: str = ""
    clickable: bool = False
    long_clickable: bool = False
    checkable: bool = False
    editable: bool = False       # an input field (EditText)
    password: bool = False
    focused: bool = False
    enabled: bool = True
    selected: bool = False
    bounds: dict[str, Any] = field(default_factory=lambda: {"center": (0, 0)})
    index: int = 0
    depth: int = 0

    def label(self) -> str:
        """Best human-facing label: visible text, else desc, else the id tail."""
        if self.text.strip():
            return self.text.strip()
        if self.content_desc.strip():
            return self.content_desc.strip()
        if self.resource_id:
            return self.resource_id.rsplit("/", 1)[-1]
        return ""

    def kind(self) -> str:
        if self.editable:
            return "field"
        if self.clickable:
            return "button"
        return "view"

    def interesting(self) -> bool:
        return bool(self.resource_id or self.text or self.content_desc
                    or self.clickable or self.editable)

    def center(self) -> tuple[int, int]:
        return tuple(self.bounds.get("center", (0, 0)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id, "text": self.text,
            "content_desc": self.content_desc, "cls": self.cls,
            "kind": self.kind(), "clickable": self.clickable,
            "long_clickable": self.long_clickable, "checkable": self.checkable,
            "editable": self.editable, "password": self.password,
            "focused": self.focused, "enabled": self.enabled,
            "selected": self.selected, "bounds": self.bounds,
            "index": self.index, "depth": self.depth,
        }


def parse_elements(hierarchy_xml: Optional[str]) -> list[Element]:
    """Every ``<node>`` of a uiautomator dump as :class:`Element`s.

    Tolerant: ``None`` or malformed XML yields ``[]`` so callers never guard it.
    """
    if not hierarchy_xml:
        return []
    try:
        root = ET.fromstring(hierarchy_xml)
    except ET.ParseError:
        return []

    out: list[Element] = []

    def walk(node: ET.Element, depth: int) -> None:
        if node.tag == "node":
            cls = node.get("class", "")
            out.append(Element(
                resource_id=node.get("resource-id", ""),
                text=node.get("text", ""),
                content_desc=node.get("content-desc", ""),
                cls=cls,
                clickable=_as_bool(node.get("clickable")),
                long_clickable=_as_bool(node.get("long-clickable")),
                checkable=_as_bool(node.get("checkable")),
                editable="EditText" in cls,
                password=_as_bool(node.get("password")),
                focused=_as_bool(node.get("focused")),
                enabled=node.get("enabled", "true") != "false",
                selected=_as_bool(node.get("selected")),
                bounds=_parse_bounds(node.get("bounds")),
                index=int(node.get("index", "0") or 0),
                depth=depth,
            ))
        for child in node:
            walk(child, depth + 1)

    walk(root, 0)
    return out


def interesting(elements: list[Element]) -> list[Element]:
    return [e for e in elements if e.interesting()]


# --- identity ----------------------------------------------------------------
def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def structural_fingerprint(activity: Optional[str], elements: list[Element]) -> str:
    """Identity of the screen's *structure* (ignores volatile text), so the same
    screen with different field contents fingerprints the same."""
    sig = "|".join(sorted(f"{e.resource_id}:{e.cls}:{e.content_desc}" for e in elements))
    return _sha1((activity or "") + "#" + sig)


def content_fingerprint(activity: Optional[str], elements: list[Element]) -> str:
    """Identity including visible text — distinguishes an error state from a
    clean one on a structurally identical screen."""
    sig = "|".join(sorted(f"{e.resource_id}:{e.cls}:{e.content_desc}:{e.text}" for e in elements))
    return _sha1((activity or "") + "#" + sig)


def window_flags(elements: list[Element]) -> dict[str, bool]:
    """Cheap overlay detection from class/id hints (a real dialog/popup)."""
    dialog = any(
        "Dialog" in e.cls or "PopupWindow" in e.cls
        or e.resource_id.endswith(("id/alertTitle", "id/parentPanel", "id/design_bottom_sheet"))
        for e in elements
    )
    return {"dialog": dialog}


# --- diff --------------------------------------------------------------------
@dataclass
class ScreenDiff:
    activity_changed: bool = False
    package_changed: bool = False
    keyboard_changed: bool = False
    structural_changed: bool = False
    added_text: list[str] = field(default_factory=list)
    removed_text: list[str] = field(default_factory=list)
    added_ids: list[str] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    summary: str = "NO_CHANGE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "activity_changed": self.activity_changed,
            "package_changed": self.package_changed,
            "keyboard_changed": self.keyboard_changed,
            "structural_changed": self.structural_changed,
            "added_text": self.added_text, "removed_text": self.removed_text,
            "added_ids": self.added_ids, "removed_ids": self.removed_ids,
        }


def screen_diff(before, after) -> ScreenDiff:
    """Compare two observation-like objects (``.activity/.package/.keyboard_visible``
    and ``.elements()``/``.texts()``) into a labelled :class:`ScreenDiff`."""
    b_els, a_els = before.elements(), after.elements()
    b_ids = {e.resource_id for e in b_els if e.resource_id}
    a_ids = {e.resource_id for e in a_els if e.resource_id}
    b_txt, a_txt = before.texts(), after.texts()

    d = ScreenDiff(
        activity_changed=before.activity != after.activity,
        package_changed=before.package != after.package,
        keyboard_changed=before.keyboard_visible != after.keyboard_visible,
        structural_changed=(before.structural_fingerprint()
                            != after.structural_fingerprint()),
        added_text=sorted(a_txt - b_txt),
        removed_text=sorted(b_txt - a_txt),
        added_ids=sorted(a_ids - b_ids),
        removed_ids=sorted(b_ids - a_ids),
    )
    if d.activity_changed or d.package_changed:
        d.summary = "NAVIGATION_DETECTED"
    elif d.structural_changed:
        d.summary = "SCREEN_CHANGED"
    elif d.added_text or d.removed_text:
        d.summary = "CONTENT_CHANGED"
    elif d.keyboard_changed:
        d.summary = "KEYBOARD_TOGGLED"
    return d


# --- candidate ranking (deterministic seed of the target resolver) -----------
@dataclass
class Candidate:
    element: Element
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        e = self.element
        return {
            "label": e.label(), "kind": e.kind(),
            "resource_id": e.resource_id, "text": e.text,
            "content_desc": e.content_desc, "score": round(self.score, 3),
            "reasons": self.reasons,
        }


def _ratio(a: str, b: str) -> float:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def rank_candidates(query: str, elements: list[Element],
                    role: Optional[str] = None, limit: int = 5) -> list[Candidate]:
    """Score elements against a human ``query`` (label/text). ``role`` biases the
    result: ``"field"`` favours editables, ``"tappable"`` favours clickables.
    Deterministic — an AI ranker can later replace this behind the same signature.
    """
    cands: list[Candidate] = []
    for e in interesting(elements):
        id_tail = e.resource_id.rsplit("/", 1)[-1] if e.resource_id else ""
        base = max(_ratio(query, e.text), _ratio(query, e.content_desc), _ratio(query, id_tail))
        score, reasons = base, []
        if base:
            reasons.append(f"text/desc/id match {base:.2f}")
        if role == "field" and e.editable:
            score += 0.2
            reasons.append("editable field +0.20")
        if role == "tappable" and e.clickable:
            score += 0.1
            reasons.append("clickable +0.10")
        if not e.enabled:
            score -= 0.2
            reasons.append("disabled -0.20")
        if score > 0:
            cands.append(Candidate(e, score, reasons))
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands[:limit]


# --- human-readable inventory ------------------------------------------------
def format_table(elements: list[Element]) -> str:
    """A markdown table of the interesting elements on a screen."""
    rows = ["| # | kind | resource_id | text | desc | flags | bounds |",
            "|---|------|-------------|------|------|-------|--------|"]
    for i, e in enumerate(interesting(elements)):
        flags = ",".join(f for f, on in (
            ("click", e.clickable), ("edit", e.editable),
            ("check", e.checkable), ("disabled", not e.enabled),
            ("pwd", e.password)) if on)
        b = e.bounds
        box = f"[{b.get('left',0)},{b.get('top',0)}][{b.get('right',0)},{b.get('bottom',0)}]"
        rows.append(f"| {i} | {e.kind()} | {e.resource_id} | "
                    f"{e.text[:30]} | {e.content_desc[:20]} | {flags} | {box} |")
    return "\n".join(rows)
