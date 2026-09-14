# Plan: Perception-first engine — shared ScreenObservation + inspection

## Context

Flows break because YAML is treated as the source of UI truth (hand-guessed
`resource-id`s), and when a step fails there's no view of what was actually on
screen. The real goal is a **Perception → Resolution → Action → Observation →
Diff → Validation → Evidence** engine where **YAML carries intent, and the engine
discovers the implementation** (which element, what changed, did it pass). The
immediate need — "fetch ids for any screen so nothing breaks" — is the
*inspection* view of that same perception layer, not a standalone scanner.

Guiding principle (from review): **one perception object** — a `ScreenObservation`
that execution, recovery, validation, reporting, and inspection all consume — so
there is one way to understand an Android screen, not five. Build the perception
foundation now; design every interface toward the target; add AI later and only
to rank ambiguous candidates, never to decide blindly.

Deliberate scoping choice: **grow the existing flat modules/dataclasses** toward
the target interfaces rather than physically restructuring into
`observation/`, `locator/`, `actions/`, `validation/` subpackages now — the engine
has 54 green tests and a working observe→act→validate loop; churn now buys
nothing. Restructure is a later, mechanical step once the interfaces settle.

## Target architecture (design intent)

```
TEST CASE (intent)
   → Action Intent → Target Resolver ─┐
                                      ▼
   PERCEPTION  (UI tree · screenshot · OCR · package/activity · window state)
                                      ▼
                               ScreenObservation
                    ┌──────────────────┴───────────────┐
              Target Resolver                     State Analyzer
                    │  Resolution                       │ ScreenDiff
                    ▼                                    ▼
                  ACTION ───────────────► observe(after) ──► VALIDATOR ──► PASS/FAIL ──► EVIDENCE
                    │  on failure: re-observe → diagnose → RECOVER → re-resolve
```

Inspection = read-only perception (serialize a `ScreenObservation`). Recovery =
re-perceive + re-resolve on the same object. Validation = reason over
before/after + `ScreenDiff`, not over selectors the YAML had to spell out.

## How this maps onto existing code (reuse, don't rewrite)

| Target concept | Existing today | Change |
|---|---|---|
| `ScreenObservation` | `models.Observation` (pkg/activity/hierarchy/screenshot/keyboard) | **extend**: add `elements`, `structural_fingerprint`, `content_fingerprint`, `window` (keyboard + dialog/overlay flags). New fields optional → backward compatible |
| perception sources | `observation.observe`, `ocr` | keep hierarchy primary; when `elements == []`, fall back to screenshot/OCR as the perception source (reuse `engine/ocr.py`) |
| `ScreenDiff` | `Observation.transition` (activity/hierarchy/text deltas) | **formalize** into a `ScreenDiff` dataclass: activity/package/keyboard changed, added/removed/changed elements, text changes, fingerprint changed, summary verdict (e.g. `NAVIGATION_DETECTED`). `validator.change_ratio`/`screen_changed` reuse it |
| `Resolution` + candidate ranking | `resolver.resolve` + `ResolutionResult(strategy, confidence, attempts)` | **evolve** into `TargetResolver → Resolution{status(EXACT/MATCHED/AMBIGUOUS/NOT_FOUND), target, candidates[], confidence, reasons[]}` scoring strategies (id/desc/text/class/clickable/bounds). Current top-confidence path preserved → tests stay green |
| failure taxonomy | `Status.BLOCKED/CRASH` | add `ActionResult.failure_reason`: `TARGET_NOT_FOUND / AMBIGUOUS / DISABLED / NOT_CLICKABLE / UNEXPECTED_SCREEN / RECOVERY_FAILED / DEVICE_ERROR / APP_CRASHED / TIMEOUT` (BLOCKED/CRASH map onto it) |
| evidence | `evidence.py` per-step png/xml/json | store full observations as `observations/obs_NNN.json`; `ActionResult` references obs ids; failures inline a **compact** inventory+candidates summary (don't duplicate full inventory per step) |
| CLI | `cli.py` flags | move toward subcommands: `run`, `inspect`, `doctor` (keep `--inspect`/`--check-env` as aliases) |

## Phase 1 — build now: perception foundation + inspection

1. **`engine/inspect.py`** (the perception helpers, consumed by `Observation`):
   - `Element` dataclass (`resource_id, text, content_desc, cls, clickable,
     long_clickable, checkable, editable, password, focused, enabled, selected,
     bounds{…,center}, index, depth`).
   - `parse_elements(hierarchy_xml)` — tolerant full-tree walk (reuse the
     `ET.fromstring` guard + bounds parse style in `models.py`/`validator.py`).
   - `structural_fingerprint` (activity + sorted `id:class:desc`) and
     `content_fingerprint` (adds visible text) — **named separately**, both stored.
   - `screen_diff(before, after) -> ScreenDiff`.
   - `format_table(obs)` for `inventory.md`; `rank_candidates(query, elements)`
     (deterministic — the seed of the Phase-2 `TargetResolver`; difflib + flag
     bonuses, no AI).
2. **Extend `engine/models.py` `Observation`**: optional `elements()` (lazy parse
   via `inspect`), `structural_fingerprint()`, `content_fingerprint()`, `window`
   flags; keep `transition` delegating to `screen_diff`. Additive only.
3. **`engine/observation.py` `observe`**: unchanged signature; populate the new
   fields + detect dialog/overlay from the hierarchy. Still one before/after per step.
4. **`cli.py` `inspect`** (`py cli.py inspect [--label N] [--serial S] [--apk A --launch]`,
   `--inspect` kept as alias): snapshot the **current** screen (any screen/popup)
   via `observe`, write a bundle `screens/<label>/{observation.json, hierarchy.xml,
   screenshot.png, inventory.md}`, print the table. Re-run per screen to build a
   real-selector library. Notes the perception source (hierarchy vs OCR-fallback).
5. **Break-time diagnostics** (`executor.py` + `models.py`): on a failed targeted
   action, set `failure_reason` and attach a compact inventory + `rank_candidates`
   suggestions to the `ActionResult`; evidence stores the full observation
   separately. Existing success paths and reports unchanged.
6. **Tests** (`tests/test_inspect.py`): `parse_elements` (attrs, editable vs
   clickable, nested, bounds/center, `[]` on malformed); structural vs content
   fingerprint (same structure + changed text → same structural, different
   content); `screen_diff` (added/removed/activity-changed → `NAVIGATION_DETECTED`);
   `rank_candidates` ordering; a BLOCKED step carries `failure_reason` + suggestions.

## Later phases (design toward, implement after Phase 1)
- **P2 Target resolution:** `TargetResolver`/`Resolution` candidate ranking replaces
  the ad-hoc selector chain (keeps current behavior as the high-confidence path).
- **P3 Semantic actions:** intent targets (`target: "Login"`, `enter_text`/`submit`)
  translated to device actions; YAML stays intent-level.
- **P4 Validation engine:** assertions consume `ScreenDiff` + before/after so most
  expectations need no explicit selectors (`visible`, `not_visible`,
  `screen_changed`, `activity_changed`, element state).
- **P5 Recovery on shared perception:** recovery re-perceives + re-resolves (e.g.
  detect a permission dialog → dismiss → re-resolve) instead of a separate path.
- **P6 CLI/agent:** `replay`, richer `doctor`; AI ranking only for AMBIGUOUS
  candidates, gated behind deterministic verification.

## Files
- New: `engine/inspect.py`, `tests/test_inspect.py`.
- Edit: `engine/models.py` (Observation fields + `ScreenDiff` + `failure_reason`),
  `engine/observation.py` (populate fields), `engine/executor.py` (break-time
  diagnostics), `engine/evidence.py` (store observations, compact failure summary),
  `cli.py` (`inspect` subcommand), `.gitignore` (`screens/`), a note in
  `docs/TEST_GUIDE.md` + `docs/index.html`.
- Reuse: `device.dump_hierarchy/screenshot`, `observation.observe`, `ocr`,
  `models._hierarchy_texts`, `validator.change_ratio`, `recovery.reach`.

## Verification
1. **Unit:** `py -m pytest -q` — existing 54 stay green (additive changes; current
   resolve/validate paths untouched) + the new `test_inspect.py` cases above.
2. **Live on Aimring:** boot `qa_test`, install `apks/app_aimring_v0.1.3.apk`,
   launch. `py cli.py inspect --label login` → bundle lists the login screen's real
   fields/buttons (ids/text/flags) + saves `screens/login/`. Drive to a popup/next
   screen, `inspect --label next` → confirms it perceives **any** screen. Force a
   wrong id in a test → the step reports `TARGET_NOT_FOUND` with the real ids +
   ranked suggestions in the evidence.
3. **Regression:** sample + Nextcloud flows pass unchanged.