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
    """A **scroll-stable** identity for de-duping and re-finding a candidate across
    scroll positions — the tap center moves when the screen scrolls, so identity is
    the resolver's own fields (id/class/text/desc), not coordinates. Two truly
    blank buttons can conflate, but those are icon chrome (deprioritised)."""
    return (el.resource_id, el.cls, el.text, el.content_desc)


# Navigation-chrome tokens (matched against resource-id / content-desc). These are
# the app's own nav affordances, not in-content actions.
_NAV_TOKENS = ("menu", "hamburger", "drawer", "navigate up", "test-cart",
               "back to", "test-back", "bottomnav", "toolbar", "tab_", "app_bar")


def _looks_nav(el) -> bool:
    """Is this control app navigation chrome (a hamburger, back arrow, cart icon,
    tab bar) rather than an in-content action?"""
    hay = (el.resource_id + " " + el.content_desc).lower()
    if any(tok in hay for tok in _NAV_TOKENS):
        return True
    # an icon-only control (no text/desc) sitting high in the app-bar region
    if not el.text.strip() and not el.content_desc.strip():
        return int(el.bounds.get("top", 0)) < 320
    return False


def _priority(el) -> int:
    """Higher = tapped sooner. In-content actions (a control with real text, e.g.
    'ADD TO CART') beat nav chrome, so a crawl reaches the content action before
    the hamburger menu — the inspector's element data drives the ordering."""
    label = (el.text.strip() or el.content_desc.strip())
    p = 2 if (len(label) >= 3 and any(c.isalpha() for c in label)) else 0
    if _looks_nav(el):
        p -= 3
    return p


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

    def _return_to_entry(top_fp: str, pre_fp: str) -> bool:
        """Back once, settle, and report whether we are back on this screen. Back
        typically restores the parent at its previous scroll position, so accept
        EITHER the top fingerprint or the pre-tap (possibly scrolled) one; when we
        return scrolled, reset to the top so the next candidate still resolves. A
        Back that escapes the app is a stop signal — never tap stale coordinates."""
        _back(device, settle_fn)
        obs = _in_app()
        if obs is None:
            return False
        cur = obs.structural_fingerprint()
        if cur == top_fp:
            return True
        if cur == pre_fp:
            _scroll_to_top()
            return True
        return False

    def _note_destructive(obs) -> None:
        for e in obs.elements():
            if e.clickable and e.enabled and not e.editable and _is_destructive(e):
                skipped.add((e.text or e.content_desc or e.resource_id or "").strip())

    def _scroll_changed(obs) -> bool:
        """Scroll forward once. True if the view changed (more may be revealed),
        False at the bottom / with no scrollable container. Compares the *raw*
        (activity, hierarchy) so a text/bounds-only change counts."""
        if not any(e.scrollable for e in obs.elements()):
            return False
        before = recovery._screen_signature(device)
        try:
            device.scroll_forward()
        except Exception:
            return False
        settle_fn(device)
        return recovery._screen_signature(device) != before

    def _scroll_to_top() -> None:
        """Drag the content back to the top (opposite of scroll_forward) so the
        prioritised tapping pass starts from a known position."""
        for _ in range(CRAWL_MAX_SCROLLS_PER_SCREEN + 1):
            before = recovery._screen_signature(device)
            try:
                device.swipe(400, 700, 400, 1700, 0.2)
            except Exception:
                return
            settle_fn(device)
            if recovery._screen_signature(device) == before:
                return

    def _gather(entry_obs) -> list[dict[str, Any]]:
        """Enumerate every safe candidate on this screen — visible AND below the
        fold — without tapping, recording each one's priority. Notes destructive
        controls in passing, then returns the screen to the top."""
        found: dict[tuple, int] = {}
        obs, scrolls = entry_obs, 0
        while True:
            _note_destructive(obs)
            for e in obs.elements():
                if _tappable(e):
                    found.setdefault(_signature(e), _priority(e))
            if scrolls >= CRAWL_MAX_SCROLLS_PER_SCREEN or not _scroll_changed(obs):
                break
            scrolls += 1
            nxt = _in_app()
            if nxt is None:
                break
            obs = nxt
        if scrolls:
            _scroll_to_top()
        return [{"sig": s, "priority": p} for s, p in found.items()]

    def _bring_into_view(sig: tuple):
        """Scroll from the top until an element with this signature is on screen;
        return it (fresh coordinates) or None if it can't be reached."""
        scrolls = 0
        while True:
            here = _in_app()
            if here is None:
                return None
            for e in here.elements():
                if _signature(e) == sig:
                    return e
            if scrolls >= CRAWL_MAX_SCROLLS_PER_SCREEN or not _scroll_changed(here):
                return None
            scrolls += 1

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

        # Gather the whole screen's candidates first (visible + below the fold),
        # then tap CONTENT ACTIONS before NAV CHROME — so a small budget reaches an
        # add-to-cart button before it is spent on the hamburger menu. Stable
        # sort keeps enumeration order within equal priority.
        candidates = sorted(_gather(obs), key=lambda c: c["priority"], reverse=True)
        tried: set[tuple] = set()
        for cand in candidates:
            if len(captured) >= max_screens or taps["n"] >= CRAWL_MAX_TAPS:
                break
            sig = cand["sig"]
            if sig in tried:
                continue
            tried.add(sig)
            el = _bring_into_view(sig)              # scroll it into view for fresh coords
            if el is None:
                continue
            here = _in_app()
            if here is None:
                break
            pre_fp = here.structural_fingerprint()  # may differ from fp when scrolled
            taps["n"] += 1
            try:
                device.tap_xy(*el.center())
            except Exception:
                continue
            settle_fn(device)
            after = observe(device)
            after_fp = after.structural_fingerprint()

            if after.package and package and after.package != package:
                if not _return_to_entry(fp, pre_fp):   # left the app — come back to entry
                    break
                continue
            if after_fp == pre_fp:
                continue                            # tap changed nothing → NO Back (root-safe)
            if after_fp in visited:
                if not _return_to_entry(fp, pre_fp):
                    break
                continue

            _explore(depth + 1)                     # captures the new screen/state
            # Return to THIS screen at its entry state; if Back overshoots or
            # leaves the app, stop — never keep scanning a different screen.
            if not _return_to_entry(fp, pre_fp):
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
