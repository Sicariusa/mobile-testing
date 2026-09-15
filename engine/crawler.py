"""Auto-crawl — bounded screen discovery that feeds the screen library.

A deterministic depth-first walk that *reuses the runner's own infrastructure*:
the same `observe()` perception, `inspect` fingerprints, and the `Device` action
seam. It is not a second engine — it discovers screens, the runner consumes them.

Safety is by construction, not by intelligence:
  * bounded — ``max_screens`` (hard-capped), ``max_depth``, and a total-tap budget
  * loop-free — a screen already seen (by structural fingerprint) is never
    re-captured or re-entered
  * non-destructive — a control whose label matches ``CRAWL_DESTRUCTIVE_LABELS``
    (logout / delete / pay / …) is never tapped; it is recorded as skipped
  * app-scoped — a tap that leaves the app package is undone with Back, not kept
  * read-only fields — editable inputs are not tapped (no typing, no keyboards)

No LLM: "is it clickable, unseen, safe? tap; did the fingerprint change? record."
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional

from . import recovery
from .config import (CRAWL_DESTRUCTIVE_LABELS, CRAWL_MAX_DEPTH,
                     CRAWL_MAX_SCREENS_DEFAULT, CRAWL_MAX_SCREENS_LIMIT,
                     CRAWL_MAX_SCROLLS_PER_SCREEN, CRAWL_MAX_TAPS)
from .device import Device
from .observation import observe
from .screen_library import ScreenLibrary
from .stabilize import settle


def _is_destructive(el) -> bool:
    hay = " ".join((el.text, el.content_desc, el.resource_id)).lower()
    return any(word in hay for word in CRAWL_DESTRUCTIVE_LABELS)


def _tappable(el) -> bool:
    """A safe crawl candidate: clickable, enabled, not an input, not destructive,
    and on-screen (a real center)."""
    return (el.clickable and el.enabled and not el.editable
            and el.center() != (0, 0) and not _is_destructive(el))


def _signature(el) -> tuple:
    """A stable identity for de-duping candidates across scroll positions —
    reuses the Element fields the resolver relies on (id/class/text/desc) plus
    the tap center, so two blank-label buttons are not conflated."""
    return (el.resource_id, el.cls, el.text, el.content_desc, el.center())


def crawl(device: Device, package: str, library: ScreenLibrary, *,
          max_screens: int = CRAWL_MAX_SCREENS_DEFAULT,
          max_depth: int = CRAWL_MAX_DEPTH,
          launch: bool = True,
          launch_activity: Optional[str] = None,
          screenshots: bool = True,
          sleep: Callable[[float], None] = time.sleep,
          settle_fn: Callable[..., bool] = settle) -> dict[str, Any]:
    """Discover up to ``max_screens`` screens and capture each new one into
    ``library``. With ``launch=False`` (the default for the panel/CLI) it starts
    from **whatever screen is already open** — drive the app to checkout, crawl,
    and the captures are the checkout flow, not the home screen. With
    ``launch=True`` it (re)launches the app to its start first. Returns a summary
    dict. ``sleep``/``settle_fn`` are injectable so tests run without a device."""
    max_screens = max(1, min(int(max_screens), CRAWL_MAX_SCREENS_LIMIT))
    if not launch and not package:
        package = _safe_pkg(device)
    visited: set[str] = set()
    captured: list[dict[str, Any]] = []
    skipped: set[str] = set()
    taps = {"n": 0}

    if launch:
        try:
            device.launch(package, launch_activity)
            sleep(1.0)
            settle_fn(device)   # let a splash/first-draw settle before observing
        except Exception:
            pass

    def _capture(obs, *, checkpoint: bool = False) -> None:
        record = library.add(obs, f"auto_{len(captured) + 1}", checkpoint=checkpoint)
        if screenshots:
            shots_dir = os.path.join(library.dir, "shots")
            try:
                os.makedirs(shots_dir, exist_ok=True)
                shot = os.path.join(shots_dir, f"{record['id']}.png")
                device.screenshot(shot)
                record["screenshot"] = shot.replace("\\", "/")
            except Exception:
                record["screenshot"] = None
        captured.append(record)

    def _in_app():
        """Observe only if we are still inside the target app; else None."""
        obs = observe(device)
        if obs.package and package and obs.package != package:
            return None
        return obs

    def _return(expected_fp: str) -> bool:
        """Back once, settle, and report whether we are back in the app on the
        screen we expected. A Back that escapes the app (or overshoots) is a
        stop signal — never keep tapping stale coordinates."""
        _back(device, settle_fn)
        obs = _in_app()
        return obs is not None and obs.structural_fingerprint() == expected_fp

    def _note_destructive(obs) -> None:
        for e in obs.elements():
            if e.clickable and e.enabled and not e.editable and _is_destructive(e):
                skipped.add((e.text or e.content_desc or e.resource_id or "").strip())

    def _reveal_scrolled(obs) -> bool:
        """Scroll to reveal more of the current screen. Returns True if the view
        actually changed (more may be revealed), False at the bottom / when there
        is no scrollable container. Compares the *raw* (activity, hierarchy) so a
        text/bounds-only change still counts — never the text-blind fingerprint."""
        if not any(e.scrollable for e in obs.elements()):
            return False
        before = recovery._screen_signature(device)
        try:
            device.scroll_forward()
        except Exception:
            return False
        settle_fn(device)
        return recovery._screen_signature(device) != before

    def _explore(depth: int) -> None:
        if len(captured) >= max_screens or taps["n"] >= CRAWL_MAX_TAPS:
            return
        obs = _in_app()
        if obs is None:                            # not in the app — bail
            return
        fp = obs.structural_fingerprint()          # entry (top) identity of this screen
        if fp not in visited:
            visited.add(fp)
            _capture(obs, checkpoint=(depth == 0))   # the screen we started on
            if len(captured) >= max_screens:
                return
        if depth >= max_depth:
            return

        # Walk this screen's safe candidates, revealing below-the-fold ones with
        # bounded scrolls. `tried` (by element signature, not label) prevents
        # re-tapping the same control across scroll positions and across the
        # re-scan that follows a child exploration.
        tried: set[tuple] = set()
        scrolls = 0
        while len(captured) < max_screens and taps["n"] < CRAWL_MAX_TAPS:
            here = _in_app()                        # always tap from a fresh, in-app view
            if here is None:
                break
            _note_destructive(here)
            cand = next((e for e in here.elements()
                         if _tappable(e) and _signature(e) not in tried), None)
            if cand is None:                        # nothing new visible — reveal more?
                if scrolls >= CRAWL_MAX_SCROLLS_PER_SCREEN or not _reveal_scrolled(here):
                    break
                scrolls += 1
                continue

            tried.add(_signature(cand))
            pre_fp = here.structural_fingerprint()  # may differ from fp when scrolled
            taps["n"] += 1
            try:
                device.tap_xy(*cand.center())       # fresh coords from `here`
            except Exception:
                continue
            settle_fn(device)
            after = observe(device)
            after_fp = after.structural_fingerprint()

            if after.package and package and after.package != package:
                if not _return(fp):                 # left the app — come back to entry
                    break
                continue
            if after_fp == pre_fp:
                continue                            # tap changed nothing → NO Back (root-safe)
            if after_fp in visited:
                if not _return(fp):
                    break
                continue

            _explore(depth + 1)                     # captures the new screen/state
            # Return to THIS screen at its entry state; if Back overshoots or
            # leaves the app, stop — never keep scanning a different screen.
            if not _return(fp):
                break

    _explore(0)
    library.save()
    checkpoint = next((r for r in captured if r.get("is_checkpoint")), None)
    return {
        "package": package,
        "max_screens": max_screens,
        "checkpoint": ({"id": checkpoint["id"], "label": checkpoint["label"],
                        "activity": checkpoint.get("activity"),
                        "screenshot": checkpoint.get("screenshot")}
                       if checkpoint else None),
        "captured": [{"id": r["id"], "label": r["label"],
                      "activity": r.get("activity"),
                      "fingerprint": r.get("structural_fingerprint"),
                      "is_checkpoint": r.get("is_checkpoint", False),
                      "screenshot": r.get("screenshot")} for r in captured],
        "screens_captured": len(captured),
        "screens_visited": len(visited),
        "skipped_destructive": sorted(s for s in skipped if s),
        "taps": taps["n"],
    }


def _safe_pkg(device: Device) -> str:
    try:
        return device.current_package() or ""
    except Exception:
        return ""


def _back(device: Device, settle_fn: Callable[..., bool]) -> None:
    try:
        device.press_back()
        settle_fn(device)
    except Exception:
        pass
