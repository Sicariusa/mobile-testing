# Plan — Scroll-aware auto-crawl + a failure-classification & evidence model

## Context

Two gaps surfaced testing the crawler live on SwagLabs:

1. **Auto-crawl misses below-the-fold controls.** `engine/crawler.py` taps only
   controls in the *current* hierarchy dump; the product screen's **Add-to-cart**
   sits under the price (off-screen), so auto-crawl never reached the add-to-cart
   / cart flow. It must *reveal* off-screen controls with bounded scrolls, reusing
   the existing perception and the `Device` seam (no second engine).

2. **A real app failure is not clearly classified or evidenced.** Rich diagnostics
   (`failure_reason`, on-screen matches, `screen_summary`) are written to
   `timeline.json` and printed to the terminal, but **`report.py` renders none of
   them**, and **failed assertions set no `failure_reason`/evidence**. So a failing
   check shows as a bare red "FAIL" with a parsed-from-`detail` line. We need a
   proper model: the **engine reports evidence, not verdicts about the app** — a
   failed assertion means *"expected behavior was not observed"* (neutral), and the
   **report layer** presents that as "Likely defect". Crucially, this must stay
   distinct from BLOCKED (*couldn't reach the target*), and expected/actual/observed
   must be **structured fields**, not strings the report re-parses.

Design principle throughout: **validator stays deterministic** — fuzzy/nearest-text
work only *enriches evidence after* the verdict, never decides it.

---

## Part A — Scroll-aware auto-crawl (on by default)

**Files:** `engine/crawler.py`, `engine/config.py`, `engine/inspect.py`.

**A1. Element scrollability (so we only scroll when it makes sense).**
- `inspect.Element`: add `scrollable: bool`; `parse_elements` reads the
  `scrollable` node attribute; include it in `as_dict`
  (`screen_library._element_from_dict` reads it, default False). Does **not**
  affect fingerprints (they key on id:class:desc).

**A2. Reveal-scroll in `crawler._explore`'s candidate loop.**
- Gather candidates from the current view; tap the safe ones (unchanged), tracking
  a `tried` set keyed by a **stable element signature**, not the label:
  `_signature(el) = (resource_id, cls, text, content_desc, center)` — reuse the
  `Element` fields the resolver already relies on (`_concrete_selector` uses
  id>text>desc); do not invent a second identity system.
- When the visible candidates are exhausted **and** the observation contains a
  scrollable container (`any(e.scrollable ...)`), `device.scroll_forward()`,
  re-observe, and append **new** `_tappable` candidates whose signature isn't in
  `tried`. Repeat up to `CRAWL_MAX_SCROLLS_PER_SCREEN`.
- **Stop scrolling on no observable change.** Use a raw before/after comparison of
  `(current_activity, dump_hierarchy)` — the same signal `recovery._screen_signature`
  returns (raw XML, so it *is* sensitive to text/bounds, not just node structure) —
  never `structural_fingerprint` (which excludes text). Verify `_screen_signature`
  returns raw XML before reusing it.
- **Never capture a scroll position as a screen** — capture stays keyed by
  structural fingerprint on genuine navigation. A revealed control that changes the
  screen *in place* (Add-to-cart → REMOVE + badge = new fingerprint) is captured as
  a new screen exactly like navigation today.

**A3. Explicit backtracking invariant.** For every explored state:
`discover candidates → execute one → explore the resulting state → return to the
parent state (Back, verified in-app on the parent fingerprint) → continue the
remaining candidates`. The candidate list and scroll are bound to the **parent**
observation, so after a child is explored the loop resumes against the parent, never
the child/scrolled view. Keep all existing safeguards (destructive denylist,
app-scope guard, root-safe Back, visited dedup, `max_screens`/`max_depth`/tap budget).

**config.py:** add `CRAWL_MAX_SCROLLS_PER_SCREEN: int = 4`.

**Reuse:** `device.scroll_forward()`; `recovery._screen_signature` (raw-XML no-progress
check); `Element` fields + `_tappable`.

**Tests (`tests/test_crawler.py`):** extend `ScriptedDevice` with a scroll counter
that changes the returned hierarchy. Assert: (a) a below-fold control revealed only
after a scroll is tapped and its resulting screen captured; (b) scrolling stops when
`(activity, hierarchy)` stops changing; (c) intermediate scroll positions are not
captured as screens; (d) a screen with **no scrollable container is never scrolled**;
(e) **backtracking** — after exploring a child, the remaining parent candidates are
still tapped (not the child's).

---

## Part B — Failure classification & structured evidence

Goal: every non-PASS step carries **structured, deterministic evidence**; the engine
stays neutral; the report *presents* the interpretation.

**B1. Neutral classification (engine/models.py).**
- Add `FailureReason.ASSERTION_FAILED` meaning **"expected behavior not observed"**
  (never "app defect" at engine level). Existing reasons stay: `BLOCKED` family
  (target unreachable), `APP_CRASHED`, `DEVICE_ERROR`. Keep the Status set
  (`PASS/FAIL/BLOCKED/CRASH/SKIPPED`) as-is; `failure_reason` is the sub-classifier.
- **Accommodate a future `ERROR`/infrastructure class** (adb dropped, emulator died,
  timeout, install failure): today these fold into `FAIL` + `DEVICE_ERROR` — keep
  them distinguishable via `failure_reason` and note that a distinct `ERROR` status
  is a later addition. No new status implemented now.

**B2. Structured assertion evidence (engine/validator.py, engine/runner.py).**
- `ValidationOutcome` gains structured fields: `expected`, `actual`,
  `observed_texts` (a bounded list of on-screen texts — evidence, **not**
  "suggestions"). The validator populates them **without changing its verdict logic**
  (it already computes expected/found). `observed_texts` may be ordered by closeness
  to `expected` for readability (enrichment only).
- `ActionResult` gains matching first-class fields `expected`, `actual`,
  `observed_texts` (serialised in `as_dict`) — the report reads these directly and
  **never parses `detail`**.
- `runner._run_assert`: on a non-PASS (FAIL) outcome set
  `failure_reason = ASSERTION_FAILED`, copy `expected`/`actual`/`observed_texts`, and
  set `screen_summary` (reuse the `{activity, element_count, window}` shape from
  `executor._diagnose`) from the **post-condition observation** the assertion checked
  (the `after`/current screenshot — the failure state, not `before`). CRASH stays CRASH.
- Do **not** repurpose the existing `suggestions` field (that stays for resolver
  ranking on BLOCKED actions).

**B3. Report presentation (engine/report.py).**
- In `_step_card`, for any non-PASS step render a structured "why" block:
  **Expected / Actual / Observed** (from the new fields), `screen_summary`, and a
  status+reason-driven **tag** — `ASSERTION_FAILED → "Likely defect"`,
  `BLOCKED → "Couldn't reach target"`, `CRASH → "App crashed"`,
  `DEVICE_ERROR → "Environment/device error"`. The tag is presentational; the engine
  data stays neutral. Ensure the **after/failure-state screenshot** is the one shown
  for a failed assertion. Render-only (data already in `timeline.json`).

**B4. Real defect scenario — SwagLabs `problem_user` (`testcases/sauce_problem_user_bug.yaml`, new).**
- Same shape as `testcases/sauce_add_to_cart.yaml`, `data.username: problem_user`,
  asserting the **correct** behavior so the app's defect makes an assertion FAIL.
- At execution: probe `problem_user` live first (drive add-to-cart / checkout,
  observe where it misbehaves), then lock the assertion onto the confirmed broken
  step. Do **not** hard-code the assertion before probing.

**B5. Deterministic tests (`tests/test_bug_report.py`, new).**
- FakeDevice observation missing the expected text → `_run_assert` yields `FAIL`,
  `failure_reason == ASSERTION_FAILED`, structured `expected`/`actual`/`observed_texts`
  (listing the real on-screen texts), and a `screen_summary`.
- **Failure-screenshot test:** the evidence/thumbnail for the failed assert is the
  post-condition (`after`) observation, not `before`.
- **`report.py` render test:** a timeline FAIL step with the new fields produces HTML
  containing Expected/Observed and the "Likely defect" tag (no string parsing).
- **Acceptance test — BLOCKED vs defect (the core distinction):**
  Case A (target absent) → `BLOCKED` / "couldn't reach target";
  Case B (target present, action succeeds, wrong outcome) → `FAIL` /
  `ASSERTION_FAILED` / "Likely defect". Two clearly different reports.

---

## Files
- **Modify:** `engine/crawler.py`, `engine/config.py`, `engine/inspect.py`,
  `engine/models.py`, `engine/validator.py`, `engine/runner.py`, `engine/report.py`
  (and `engine/screen_library.py::_element_from_dict` for the new `scrollable` key).
- **New:** `testcases/sauce_problem_user_bug.yaml`, `tests/test_bug_report.py`;
  extend `tests/test_crawler.py`.
- **Reuse:** `device.scroll_forward`, `recovery._screen_signature` (raw-XML),
  `executor._diagnose` (screen_summary shape), `Element` fields, existing `report.py`
  card scaffolding, `sauce_add_to_cart.yaml` as template.

## Verification
1. `py -m pytest -q` — all green incl. new scroll-crawl + bug-report tests
   (backtracking, no-scroll-without-container, BLOCKED-vs-defect, failure screenshot).
2. **Scroll-crawl live:** on the product screen,
   `py cli.py crawl --package com.swaglabsmobileapp --max-screens 3` now reveals +
   taps Add-to-cart and captures the REMOVE/added state (previously stopped at
   product + menu). Confirm in the panel + a rebuilt gallery report.
3. **Bug flagging live:** run `testcases/sauce_problem_user_bug.yaml` → overall FAIL;
   terminal names the failed assertion with Expected/Actual/Observed + screen; open
   `reports/<run>/report.html` and confirm the step shows structured Expected /
   Observed, the **post-condition** screenshot, and the **"Likely defect"** tag.
   Run a target-missing case and confirm it reads as **BLOCKED / "couldn't reach
   target"** — the two are visibly different.
4. Re-run `standard_user` `sauce_add_to_cart.yaml` → still **PASS 14/14** (no
   regression); scroll-aware crawl touches only the crawler, not the run path.
