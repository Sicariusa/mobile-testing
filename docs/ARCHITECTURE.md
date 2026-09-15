# Architecture

A complete walkthrough of how the runner is put together — the perception-first
engine, every layer and module, how a step flows end to end, and the two surfaces
(CLI and web panel) on top. Written so a newcomer can find their way around and
extend it safely.

---

## 1. What this is, in one paragraph

You describe a test in YAML using **intent** — visible labels, not resource-ids
(`tap "add to cart"`, `enter_text "Username"`). The engine perceives the live
screen into a structured model, **resolves** each label to a concrete control
(learning and caching the real selector), performs the action, **recovers** when
a target isn't immediately reachable (wait / dismiss keyboard / dismiss dialog /
scroll / OCR), and **validates** the outcome deterministically. Everything above
the device is exercised in tests against a `FakeDevice` with no Android present.

The design rule that makes this tractable: **one `Observation` per screen state,
consumed by every layer** (resolution, recovery, validation, inspection), instead
of each layer re-reading the device.

---

## 2. The layers and surfaces

```
   CLI (cli.py)                 Web panel (webapp/)
        └───────────────┬───────────────┘         two surfaces, same engine
                        │
   ┌────────────────────▼────────────────────┐
   │  ORCHESTRATION   runner.py               │  load YAML → loop steps → persist
   └────────────────────┬────────────────────┘
                        │
   ┌────────────────────▼────────────────────┐  executor.py  perform a step
   │  EXECUTION       validator.py            │  validator.py decide PASS/FAIL
   │                  recovery.py             │  recovery.py  reach a hard target
   └────────────────────┬────────────────────┘
                        │
   ┌────────────────────▼────────────────────┐  observation.py  snapshot a screen
   │  PERCEPTION      inspect.py              │  inspect.py      parse + rank + fingerprint
   │                  resolver.py  ocr.py     │  resolver.py     label → concrete control
   │  selector_cache.py  screen_library.py    │  stabilize.py    wait for the screen to settle
   └────────────────────┬────────────────────┘
                        │
   ┌────────────────────▼────────────────────┐  device.py
   │  DEVICE          device.py               │  the ONLY code that touches ADB /
   │                  AndroidDevice/FakeDevice│  uiautomator2. Abstract Device + Element.
   └────────────────────┬────────────────────┘
                        │
                   Android app

   ┌──────────────────────────────────────────┐
   │  EVIDENCE  evidence.py  report.py         │  steps/, timeline.json, report.html
   └──────────────────────────────────────────┘
```

**The golden rule:** everything above the device layer reaches the device only
through the `Device` interface. That single abstraction is what lets the entire
engine run against a `FakeDevice` — swap `AndroidDevice` for `FakeDevice` and
nothing else changes. It is also the seam a future autonomous planner would sit
above, consuming `Observation` + `ActionResult` and deciding the next step.

### Debug map

| Symptom | Look at |
|---|---|
| can't connect / install | [`device.py`](../engine/device.py) |
| can't see the UI | [`observation.py`](../engine/observation.py) |
| screen model looks wrong | [`inspect.py`](../engine/inspect.py) (`parse_elements`) |
| can't find a control | [`resolver.py`](../engine/resolver.py) → [`ocr.py`](../engine/ocr.py) |
| finds the wrong control | [`inspect.py`](../engine/inspect.py) (`rank_candidates`, role gate) |
| target never reached | [`recovery.py`](../engine/recovery.py) |
| action didn't happen | [`executor.py`](../engine/executor.py) |
| wrong PASS/FAIL | [`validator.py`](../engine/validator.py) |
| runs feel slow | [`device.py`](../engine/device.py) memo, `config.HIERARCHY_CACHE` |
| report looks wrong | [`evidence.py`](../engine/evidence.py) / [`report.py`](../engine/report.py) |

---

## 3. Shared data models (`engine/models.py`)

Every module speaks these instead of ad-hoc dicts. They serialise to JSON via
`as_dict()`, so they flow straight into `timeline.json` and the HTML report.

- **`Observation`** — a snapshot of the device at one instant: `timestamp`,
  `package`, `activity`, `screenshot_path`, `hierarchy_xml`, `keyboard_visible`.
  It grows richer perception lazily (importing `inspect` only when asked, to
  avoid a cycle): `elements()` (parsed + cached per instance),
  `structural_fingerprint()`, `content_fingerprint()`, `window()`, `texts()`.
  `Observation.transition(before, after)` is a pure diff (no device access).
- **`ResolutionResult`** — how a target was located. On success exactly one of
  `element` (a device handle, confidence 1.0) or `coordinates` (OCR tap center,
  confidence = OCR score) is set. Carries `strategy`
  (`resource_id`/`text_exact`/`text_contains`/`desc`/`ocr`/`ranked`), a `status`
  (`EXACT`/`MATCHED`/`AMBIGUOUS`/`NOT_FOUND`), the ranked `candidates`, human
  `reasons`, the ordered `attempts`, and `bound_selector` (the concrete selector
  that was cached).
- **`RecoveryTrace`** — the ordered story of reaching a stubborn target
  (immediate → retry → keyboard → dialog → scroll → OCR).
- **`ActionResult`** — the full outcome of one step. `resolved_by` / `validated_by`
  (each with a confidence) are **first-class**, plus `recovery`, `before`/`after`
  observations, `crash_signature`, and the diagnostics triplet
  `failure_reason` + `suggestions` (ranked on-screen matches) + `screen_summary`.

Enums/constants also live here: `Status` (`PASS`/`FAIL`/`BLOCKED`/`CRASH`/`SKIPPED`),
the strategy names, the `RESOLVE_*` statuses, and `FailureReason`
(`TARGET_NOT_FOUND`, `TARGET_AMBIGUOUS`, `TARGET_DISABLED`,
`TARGET_NOT_CLICKABLE`, `UNEXPECTED_SCREEN`, `RECOVERY_FAILED`, `DEVICE_ERROR`,
`APP_CRASHED`, `TIMEOUT`).

---

## 4. Perception layer (`engine/inspect.py`)

The shared, engine-independent perception helpers. No dependency on the rest of
the engine, so `Observation` consumes it lazily.

- **`Element`** — one accessibility-tree node with everything a locator needs:
  `resource_id`, `text`, `content_desc`, `cls`, `clickable`, `editable`
  (class ends in `EditText`), `enabled`, `bounds`/`center`, `index`, `depth`,
  and **`parent_index`** (the position of its parent Element in the flat list).
  Helpers: `label()`, `kind()` (field/button/view), `interesting()`, `center()`.
- **`parse_elements(xml)`** — a tolerant tree walk (`[]` on malformed XML) that
  records `parent_index` as it descends, so a match can be promoted to a
  clickable ancestor later.
- **Screen identity — the two fingerprints:**
  - `structural_fingerprint(activity, elements)` = `sha1(activity + sorted
    id:class:desc)`. **Text-independent** — the same screen with different field
    contents fingerprints the same. This is the key the selector cache and the
    screen library match on.
  - `content_fingerprint(...)` also folds in `text` — distinguishes an error
    state from a clean one on a structurally identical screen.
- **`window_flags(elements)`** — cheap dialog/popup detection from class/id hints.
- **`screen_diff(before, after)`** → a labelled `ScreenDiff`
  (`NAVIGATION_DETECTED` / `SCREEN_CHANGED` / `CONTENT_CHANGED` /
  `KEYBOARD_TOGGLED` / `NO_CHANGE`).
- **`rank_candidates(query, elements, role, limit=5)`** — the heart of intent
  resolution. For each interesting element it computes a **`base`** score
  (`difflib` similarity over text / desc / id-tail; exact = 1.0, substring = 0.9)
  and a **`score`** (base + role bonuses: editable +0.20 for a field, clickable
  +0.10 for a tap, disabled −0.20). Two deliberate mechanics:
  - **`base` vs `score` split.** Acceptance gates on `base` (pure text match);
    `score` only *orders*. A role bonus can never push a weak text match over the
    acceptance threshold.
  - **Clickable-ancestor promotion.** When a `tappable` query matches a
    *non-clickable* label with `base ≥ 0.60` (e.g. a product title inside a
    clickable card that has no label of its own), it walks `parent_index` up to
    the nearest clickable, enabled ancestor and adds that as a candidate. This is
    what makes `tap "Sauce Labs Backpack"` work when only the card is clickable.

---

## 5. The device seam + the hierarchy memo (`engine/device.py`)

`Device` is the abstract interface; `AndroidDevice` (uiautomator2 + adb) and
`FakeDevice` (tests) implement it. `_U2Element` wraps a uiautomator2 selector and
holds an `owner` back-reference so a click/set_text can invalidate the memo.

**The hierarchy memo (speed).** Reading the live tree (`dump_hierarchy`) is a
slow adb uiautomator dump; the resolver, recovery's no-progress check, and
`window()` all want to read the *same* screen back-to-back. So `AndroidDevice`
**memoizes** `dump_hierarchy()` and `current_activity()` within one screen state
([device.py:222](../engine/device.py:222)), gated by `config.HIERARCHY_CACHE`.
Every mutating call — `tap_xy`, `input_text`, `scroll_forward`, `press_back`,
`swipe`, `launch`, `clear_data`, and element `click`/`set_text` via the owner
ref — calls `invalidate()`. Two consumers must see change, so they force-fresh by
calling `invalidate()` before reading: `settle()` (it exists to detect change)
and recovery's wait loop (it's waiting for async change). Measured live: **23 → 6
dumps (74% fewer), 51 s → 29 s** on `sauce_vague.yaml`. `FakeDevice` has a no-op
`invalidate()` so the interface matches.

> **Architectural guarantee — one hierarchy snapshot per screen state.** Within a
> single screen state, resolution, recovery, verification, selector ranking and
> debug all consume the *same* dump; only a mutating action (which invalidates)
> or a consumer that must detect change (`settle`, recovery's wait loop, which
> force-fresh) triggers a new one. This is the single most important engine-
> efficiency invariant — more than anything in the panel. The memo is where it is
> enforced; adding a new consumer means reading through the memo, never issuing a
> fresh `dump_hierarchy()` of your own.

---

## 6. Observation (`engine/observation.py`)

`observe(device, screenshot_path=None)` snapshots package, activity, hierarchy,
keyboard state, and (optionally) a screenshot into one `Observation`. Each
sub-probe is guarded, so a single flaky reading yields a partial snapshot rather
than aborting. Called once before and once after every step.

---

## 7. Resolver — label → concrete control (`engine/resolver.py`)

`resolve()` locates a target on the **current** screen (no scrolling, no waiting)
in a fixed four-stage order, recording every attempt:

1. **Explicit selectors → `EXACT`.** If the YAML gave an `id`/`text`/`desc`, try
   them directly (`resource_id`, `text_exact`, `text_contains`, `desc`).
   A direct hit is confidence 1.0.
2. **Cache fast-path → `MATCHED`.** Look up `(structural_fingerprint, role,
   normalized_query)` in the `SelectorCache`. If a learned concrete selector
   still resolves, use it. If it's stale, fall through (self-healing) rather than
   fail.
3. **Inventory candidate ranking → `MATCHED`/`AMBIGUOUS`.** Rank the label
   against the parsed elements. Acceptance requires **`base ≥ RESOLVE_MIN_SCORE`
   AND role fitness** — a strong text match on a wrong-role element (a "Sign in"
   *heading* when we need the Login *button*) is recorded as `role_rejected` and
   skipped. The winner's concrete selector is verified against the live tree and
   **learned into the cache**. Top-two within `RESOLVE_AMBIGUOUS_GAP` ⇒
   `AMBIGUOUS`.
4. **OCR fallback → `MATCHED`.** Only when selectors can't reach it: find the
   label on the screenshot, return tap coordinates with the OCR confidence.

The **role gate** (`_role_ok`) is the rule that a `field` match must be editable
and a `tappable` match must be clickable — the single most important correctness
guard in resolution.

`find_with_scroll()` is a selector-only variant that scrolls forward up to
`RESOLVER_MAX_SCROLLS` passes to bring an off-screen target into view.

---

## 8. Self-healing selector cache (`engine/selector_cache.py`)

`SelectorCache(package)` persists to `.selector-cache/<package>.json`, keyed by
`(structural_fingerprint | role | normalized_query)` so a popup and the base
screen never collide and a re-visited screen reuses its binding. It **learns** a
concrete selector on first resolve and **reuses** it on later runs; a binding
that no longer resolves is simply re-bound on the next scan. The runner writes
the learned map to `reports/<run>/bindings.json` as evidence of auto-binding.

---

## 9. Screen library + preflight + directed scroll (`engine/screen_library.py`)

A reusable, per-app map of the screens the user chose to test, captured up front
by driving the app (`inspect --into-library`). Persists to
`screens/<package>/library.json`. Each entry is a **ScreenRecord** with an
**immutable id** (`scr_…`) plus `label`, `package`, `activity`,
`structural_fingerprint`, `content_fingerprint`, `screenshot`, `captured_at`, and
the full element inventory (the same bundle shape `cli.py inspect` writes — the
inspector stays the single writer).

**Identity is the id, never the label.** The label is human-facing only, so it
may be edited or duplicated freely. `get`/`remove`/`rename` all operate **by id**
— a duplicate or renamed label can never delete the wrong capture. `add()`
re-captures a label **in place, keeping its id** (a stable handle). A migration
backfills ids onto any legacy entry on load. A `structural_fingerprint` is
*evidence of a possible duplicate* (`duplicates()` reports fingerprints shared by
more than one record), **never proof a capture is invalid**: two structurally
different states can share an element count yet mean different things — the reason
the panel also shows a thumbnail.

- **`match(fingerprint)`** — the captured entry whose *structural* fingerprint
  equals the current screen's (the same identity test the cache uses).
- **`find_bearing(query, role)`** — across *all* captured screens, the best
  element matching `query` (via `rank_candidates`, `base ≥ 0.60`) and its
  captured center. This is a **hint for where an off-screen target lives**, so
  recovery can scroll *toward* it instead of blindly.
- **The label is cosmetic.** Matching is by fingerprint (the app's real activity
  + structure); the name you type is a human tag and nothing resolves on it.
- **Preflight** (`cli.py --preflight`, `webapp GET /api/preflight`) reads the
  library with **no device** and reports, per target, `✓ found on '<screen>'` or
  `✗ not captured` — a millisecond dry-check before spending a live run.

---

## 10. Recovery ladder (`engine/recovery.py`)

`reach()` escalates in bounded stages, recording each on a `RecoveryTrace`; if
nothing works it returns `(None, trace)` and the caller reports `BLOCKED`:

1. **Immediate** — `resolve()` now (selectors → cache → ranking; OCR saved for
   last).
2. **Wait / retry** — up to `RECOVERY_MAX_RETRIES`, invalidating the memo each
   pass (waiting for async change); breaks early if the screen signature is
   unchanged (no point retrying a static screen).
3. **Dismiss keyboard** — if it's covering the target, `press_back` and retry.
4. **Dismiss dialog** — if `window_flags` sees a dialog/permission overlay, tap a
   known dismiss label (`Allow`, `While using the app`, `OK`, …) or `press_back`,
   then retry.
5. **Scroll into view** — up to `RECOVERY_MAX_SCROLLS`. If a `library` is present
   and `find_bearing` knows the target was captured elsewhere, that bearing is
   recorded (the scroll is deliberate, not a guess). Breaks early when a scroll
   produces no screen change.
6. **OCR** — last resort.

---

## 11. Executor loop (`engine/executor.py`)

For an **action** step:

```
before = observe(device)
if targeted (tap/type/long_click/enter_text/submit):
    hide keyboard (for tap/submit/long_click — it obscures buttons and its
                   IME key would win the submit ranking)
    resolution, recovery = reach(target, role, cache, library)   # the ladder above
    if not resolution.found:
        after = observe(device)
        return BLOCKED  +  _diagnose(): failure_reason, ranked suggestions, screen summary
    perform(action, resolution, value)     # element.click / set_text, or tap_xy + input_text
settle(device)                             # wait for the screen to stabilise
after = observe(device)
status = CRASH if fatal-in-logcat else PASS
```

Notes:
- **`submit`** with no target tries a list of common submit labels
  (`Submit`/`Continue`/`Next`/`Sign in`/`Log in`/`Login`/`Done`/`Confirm`) on the
  current screen before falling back to the recovery ladder.
- **`enter_text`** is `type` into a field found by label; the perform verb maps
  accordingly.
- A settle timeout is not fatal — it's recorded as `detail = "screen settle
  timeout"`.
- **Assertions are handled by the runner, not the executor**, because a
  `screen_changed` / `activity_changed` assertion must reason over the
  *preceding action's* before/after — an assert step performs no action of its
  own.

---

## 12. Stabilisation (`engine/stabilize.py`)

`settle()` blocks until the screen is stable or `SETTLE_TIMEOUT_S` elapses:
two hierarchy dumps ~`SETTLE_POLL_INTERVAL_S` apart match and the activity is
unchanged. It calls `invalidate()` before every read so it sees the live screen,
never the memo. Optionally (`SETTLE_REQUIRE_SCREEN_STABLE`) it also waits for two
screenshots to be pixel-idle. Returns True on observed stability, False on
timeout.

---

## 13. Validation (`engine/validator.py`)

Deterministic, fixed-order. The **crash gate always runs first** (any
`FATAL_LOGCAT_MARKERS` line ⇒ `CRASH` + `crash_signature`). Then it is **per
assertion type** — never a generic fallback chain:

| type | how it passes |
|---|---|
| `text_exists` | hierarchy match → else OCR ≥ `OCR_MIN_CONFIDENCE` → else FAIL |
| `ocr_text_exists` | OCR only |
| `element_exists` | id/text/desc present in the hierarchy |
| `activity_is` | current activity matches (equals / endswith / contains) |
| `screen_changed` | `change_ratio(before, after) ≥ CHANGE_MIN` |
| `not_visible` | inverse of `text_exists` — the string is gone from tree **and** screen |
| `activity_changed` | `before.activity != after.activity` |

`change_ratio` = **max** of a normalised hierarchy diff and a screenshot
pixel-diff ratio.

> **Design guard:** `screen_changed` is the *only* assertion validated by change
> detection, and it is **evidence of a state transition, not semantic proof** of
> any other expectation. A tap that lands on an error screen changes the screen
> but is not a success — so `text_exists("Welcome")` must fail there, and does
> (`tests/test_validator.py::test_error_screen_does_not_pass_success_assertion`).

---

## 14. Runner — the top loop (`engine/runner.py`)

`run(testcase, device, apk_path=…)`:

1. Load + validate the YAML (or accept an already-parsed dict).
2. Build an `Evidence` sink, a `SelectorCache(package)`, and a
   `ScreenLibrary(package)`; optionally install the APK.
3. Iterate steps. **ACTION** steps go through `executor.execute` (threaded with
   the cache **and** library); **ASSERT** steps go through `_run_assert`, which
   feeds `screen_changed`/`activity_changed` the *preceding* action's
   before/after and everything else the current screen.
4. Stop on the first `CRASH` or `BLOCKED`; mark the rest `SKIPPED`.
5. Persist: per-step evidence, `logcat.txt`, `bindings.json` (what the cache
   learned), `timeline.json`, and the rendered `report.html`.
6. Return `{overall, run_id, report_path, timeline_path, counts, results}`.

`overall` is the worst status present (CRASH > BLOCKED > FAIL > PASS).

---

## 15. Evidence + report (`engine/evidence.py`, `engine/report.py`)

`Evidence` writes each step's before/after screenshots and the `ActionResult`
into `reports/<run>/steps/<n>/`, accumulates the `timeline`, and writes
`timeline.json`. `report.render()` turns the timeline into a self-contained
`report.html` with thumbnails (`THUMBNAIL_MAX_WIDTH`). Both are pure consumers of
the JSON the models already produce.

---

## 16. Configuration (`engine/config.py`)

Every tunable in one place — no other module hard-codes a threshold:
`OCR_MIN_CONFIDENCE`, `OCR_BACKEND`, `CHANGE_MIN`, the settle timings,
`HIERARCHY_CACHE`, recovery/scroll bounds (`RECOVERY_MAX_RETRIES`,
`RECOVERY_MAX_SCROLLS`, `RESOLVER_MAX_SCROLLS`), the ranking thresholds
(`RESOLVE_MIN_SCORE`, `RESOLVE_AMBIGUOUS_GAP`), `THUMBNAIL_MAX_WIDTH`, and
`FATAL_LOGCAT_MARKERS`.

---

## 17. Surfaces on top

### CLI (`cli.py`)
`run` (default), `doctor` (env check), `inspect` (dump the live screen; with
`--into-library` capture it into the screen library), `screens` (list the
library), `--preflight` (match a test to the library, no device), `replay`
(re-print a run's verdicts from `timeline.json`), `--dry-run` (print the step
plan), and `web` (launch the panel). A non-PASS run prints per-step diagnostics
(`_print_diagnostics`): the reason, the screen, and the nearest ranked matches.

### Web control panel (`webapp/`)
A stdlib `http.server` (`webapp/server.py`) + one static page
(`webapp/index.html`), no new dependencies. Every endpoint is a thin call into
the same engine functions the CLI uses — no engine logic is duplicated:
`GET /api/{env,testcases,screens,reports,avds,apks,preflight}`,
`POST /api/{inspect,run,emulator,launch,screens/remove,screens/rename}`; report
and screenshot files are served through path-escape guarded `/reports/` and
`/screens/` routes.
The panel drives the whole loop from the browser — start/stop the emulator,
launch an app, capture screens, preflight, install-and-run, read diagnostics and
reports. See [`WEB_PANEL_GUIDE.md`](WEB_PANEL_GUIDE.md).

---

## 18. How one step flows

```
runner ──▶ executor.execute(step, cache, library)
              observe() ─────────────▶ Observation (before)
              reach(target) ─────────▶ resolve: selectors → cache → ranking(role gate,
                │                        clickable ancestor) → OCR; escalate on miss
                │                        (retry / keyboard / dialog / scroll[bearing] / OCR)
              perform(...)             element.click / set_text, or tap_xy + input_text
              settle() ──────────────▶ wait for stability (bypasses the memo)
              observe() ─────────────▶ Observation (after)
           ◀── ActionResult(status, resolved_by, recovery, before/after,
                            failure_reason + suggestions + screen_summary on a miss)
runner ──▶ validator.validate(assert, before, after, logcat) ─▶ ValidationOutcome
runner ──▶ evidence.save_step(ActionResult) ─▶ steps/<n>/…, timeline.json
runner ──▶ report.render(timeline) ─▶ report.html
```

---

## 19. Where to start reading

1. [`engine/models.py`](../engine/models.py) — the vocabulary.
2. [`engine/inspect.py`](../engine/inspect.py) — how a screen becomes queryable
   (`parse_elements`, fingerprints, `rank_candidates`).
3. [`engine/runner.py`](../engine/runner.py) — the top loop; follow one step.
4. [`engine/resolver.py`](../engine/resolver.py) +
   [`engine/executor.py`](../engine/executor.py) — the core decisions.
5. `tests/test_runner.py` + `tests/fake_device.py` — the whole thing exercised
   end to end without a device.

---

## 20. Extending it

**Add a new action** (e.g. `pinch`):
1. Add the verb to `KNOWN_ACTIONS` (and `TARGETED_ACTIONS` if it needs a target)
   in [`engine/loader.py`](../engine/loader.py).
2. Handle it in `executor.execute` / `_perform`.
3. Add the primitive to the `Device` interface and both implementations
   (`AndroidDevice`, `FakeDevice`), and call `invalidate()` if it mutates the UI.

**Add a new assertion type** (e.g. `toast_shown`):
1. Add it to `ASSERT_TYPES` in `engine/loader.py`.
2. Add a branch in `validator.validate` returning a `ValidationOutcome` with the
   right `validated_by`.
3. Cover it in `tests/test_validator.py`.

**Add a resolution strategy** (e.g. an ML ranker): it slots in behind
`resolver.resolve` / `inspect.rank_candidates` — same signature, deterministic
contract. The role gate and the `base`/`score` split are the invariants to keep.

**Add a web-panel action:** add a thin endpoint in `webapp/server.py` that calls
an existing engine function, and a control in `webapp/index.html`. The server is
the seam — new options don't touch the engine.

**Swap in a live device:** construct `AndroidDevice` via `device.connect()`
instead of `FakeDevice`. Nothing above the device layer changes — that seam is
what the whole design is built around.
