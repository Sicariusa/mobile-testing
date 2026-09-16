"""SelectorCache — remember which concrete selector a label bound to, per screen.

Keyed by ``(structural_fingerprint, role, normalized_query)`` so a popup and the
base screen never collide and the same label on a re-visited screen reuses its
binding. Self-healing: a cached selector that no longer resolves is simply
re-bound by the resolver on the next scan.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from .atomicio import write_json_atomic


def norm_query(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


class SelectorCache:
    def __init__(self, package: str, base_dir: str = ".selector-cache"):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", package or "app")
        self.path = os.path.join(base_dir, f"{safe}.json")
        self.data: dict[str, Any] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    @staticmethod
    def _key(fingerprint: str, role: str, query: str) -> str:
        return f"{fingerprint}|{role}|{norm_query(query)}"

    def get(self, fingerprint: str, role: str, query: str) -> Optional[dict[str, Any]]:
        return self.data.get(self._key(fingerprint, role, query))

    def put(self, fingerprint: str, role: str, query: str, selector: dict[str, Any]) -> None:
        self.data[self._key(fingerprint, role, query)] = selector

    def bindings(self) -> dict[str, Any]:
        return dict(self.data)

    def save(self) -> None:
        write_json_atomic(self.path, self.data)
