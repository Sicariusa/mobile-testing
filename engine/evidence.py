"""Evidence — persist everything a run produces under reports/<run_id>/.

Layout::

    reports/<run_id>/
      steps/<n>/
        before.png        (written by observe via the path we hand out)
        after.png
        hierarchy.xml     (the after-hierarchy)
        step.json         (the full ActionResult, incl. recovery + OCR matches)
      logcat.txt
      timeline.json       (the whole run, drives the HTML report)
      report.html         (written by report.py)

The before/after screenshot *paths* are created here and handed to the executor
so the engine and the evidence store agree on where artifacts live.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from .models import ActionResult


class Evidence:
    def __init__(self, run_id: str, base_dir: str = "reports"):
        self.run_id = run_id
        self.run_dir = os.path.join(base_dir, run_id)
        self.steps_dir = os.path.join(self.run_dir, "steps")
        os.makedirs(self.steps_dir, exist_ok=True)
        self.timeline: list[dict[str, Any]] = []

    # -- per-step artifact paths ---------------------------------------------
    def step_dir(self, n: int) -> str:
        path = os.path.join(self.steps_dir, str(n))
        os.makedirs(path, exist_ok=True)
        return path

    def screenshot_paths(self, n: int) -> tuple[str, str]:
        d = self.step_dir(n)
        return os.path.join(d, "before.png"), os.path.join(d, "after.png")

    # -- persistence ----------------------------------------------------------
    def save_step(self, n: int, result: ActionResult) -> None:
        d = self.step_dir(n)
        record = result.as_dict()
        record["index"] = n

        # after-hierarchy as its own artifact
        if result.after and result.after.hierarchy_xml:
            with open(os.path.join(d, "hierarchy.xml"), "w", encoding="utf-8") as fh:
                fh.write(result.after.hierarchy_xml)

        # relative thumbnail paths for the report (report.html sits in run_dir)
        record["before_thumb"] = _rel_if_exists(self.run_dir, result.before)
        record["after_thumb"] = _rel_if_exists(self.run_dir, result.after)

        with open(os.path.join(d, "step.json"), "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        self.timeline.append(record)

    def write_logcat(self, text: str) -> None:
        with open(os.path.join(self.run_dir, "logcat.txt"), "w", encoding="utf-8") as fh:
            fh.write(text or "")

    def write_bindings(self, bindings: dict[str, Any]) -> str:
        """The label→selector map the resolver learned this run (viewable)."""
        path = os.path.join(self.run_dir, "bindings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(bindings, fh, indent=2, ensure_ascii=False)
        return path

    def write_timeline(self, meta: dict[str, Any]) -> str:
        payload = {"meta": meta, "steps": self.timeline}
        path = os.path.join(self.run_dir, "timeline.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return path


def _rel_if_exists(run_dir: str, obs) -> Optional[str]:
    if not obs or not obs.screenshot_path or not os.path.exists(obs.screenshot_path):
        return None
    return os.path.relpath(obs.screenshot_path, run_dir)
