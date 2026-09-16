# Changelog

All notable changes to the mobile-testing engine are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — Adversarial audit: verified fixes + live-safe reverts

A full-repository, multi-agent **adversarial audit** (29 verified findings, health
54/100 — report in [`docs/audit/`](docs/audit/AUDIT-2026-09-16.md)) followed by a
round of fixes. Several fixes were then **reverted** because they changed
real-device behaviour and only the FakeDevice suite validated them — see
[`docs/audit/AUDIT-AND-FIXES.md`](docs/audit/AUDIT-AND-FIXES.md) for the full
story. Net effect: `main`'s live behaviour is preserved; only result-neutral
improvements ship, plus the two false-verdict fixes as **opt-in**.

### Added / Fixed (result-neutral — kept)

- **Report no longer inlines full hierarchy XML** (`engine/report.py`) — the raw
  timeline block strips each step's before/after `hierarchy_xml` (still persisted
  in `timeline.json` and every `step.json`), so a large-tree report no longer
  balloons to multiple MB. Also: header counts use `.get('status', …)` so one
  malformed step can't `KeyError` the whole report; point-in-time assertions no
  longer render a fabricated duplicate "before" thumbnail.
- **Collision-proof `run_id`** (`engine/runner.py`) — a short random suffix is
  appended to the timestamp, so two runs starting in the same second (threaded
  webapp, double-clicked Run, fast batches) no longer overwrite each other's
  `reports/<run_id>/`.
- **Atomic library / selector-cache writes** (`engine/atomicio.py`, new;
  `screen_library.py`, `selector_cache.py`) — saves go through a temp file +
  `os.replace`, so a crash or concurrent reader never sees a half-written file;
  IO errors are still swallowed so a transient failure can't abort a run. The
  package sanitiser now rejects `.`/`..` so a request-controlled package can't
  point the store outside its directory.
- **Loader rejects an unusable `element_exists`** (`engine/loader.py`) — an
  assertion with only `value` (never matched by the validator) is now rejected up
  front instead of always FAILing at run time; use `id`/`text`/`desc`.
- **Resolver ranks the full candidate set** (`engine/resolver.py`) — a
  correct-role target is no longer truncated out of the top-5 by higher-scoring
  wrong-role elements before the role/base filter runs.
- **Real `long_click`** (`engine/device.py`, `engine/executor.py`) — a `long_click`
  action performs an actual long press (u2 `long_click`, coordinate fallback)
  instead of a silent short tap.
- **Per-screenshot OCR memoisation** (`engine/ocr.py`) — `_load_words` is memoised
  by `(path, mtime)`, and assertion OCR evidence is only collected when OCR is
  relevant, so a `text_exists` satisfied by the hierarchy no longer pays a full
  Tesseract pass.
- **Opt-in strict text matching** (`engine/validator.py`) — `text_exists` /
  `not_visible` accept `match: word` (whole-word / contiguous-token) or
  `match: exact`; the **default stays `contains`** (substring), so existing test
  cases are unchanged. `activity_is` now matches on a component boundary
  (`.HomeActivity` matches a fully-qualified name; a bare token in a longer
  activity does not). A numeric assertion `value` is coerced to a string instead
  of crashing, and an unexpected error in a step is caught so the run still writes
  its report.

### Reverted (behaviour changes that broke live runs)

These audit fixes passed 150+ FakeDevice tests but changed real-device behaviour;
reverted to match `main` after a live run surfaced the breakage:

- **Keyboard dismissal** kept as **BACK** (an attempt to use ESCAPE / keyevent 111
  left the soft keyboard up on real IMEs, covering the target on every
  type→tap flow).
- **`settle()`** kept responsive (an added pre-action-baseline wait + two-stable-
  pair requirement stalled live runs up to ~timeout/2 per step). Kept only the
  safe guard that a failed dump is never treated as settled.
- **Whole-word text/OCR matching** made **opt-in** rather than the default;
  `not_visible` no longer FAILs when OCR can't run; per-step crash gate kept as a
  full logcat scan; hierarchy diff kept as the full ratio.

### Verified live

Add-to-cart flow run on a real emulator on **both branches** → identical
**PASS 14/14** (incl. the type→submit keyboard step). Every web-panel feature
(env, launch, capture, screens, preflight, run, reports, static serving) driven
through the UI and over HTTP → identical on both branches. Auto-crawl excluded
(pre-existing, unrelated to this work).


## [Unreleased] — Speed, screen library, web panel

Follow-up round: make runs fast, add a pre-fetched screen library, and a local
web control panel. Builds on the perception-first engine below.

### Added

- **Context-aware, scroll-aware auto-crawl** (`engine/crawler.py`,
  `engine/inspect.py`) — the crawler no longer taps the first visible control and
  get "lost" in the app-bar. It now **gathers every candidate on a screen first**
  (visible *and* below the fold, via bounded reveal-scrolls) and taps **in-content
  actions before navigation chrome**, using the inspector's element data to
  classify each (`_priority`/`_looks_nav`: real-text controls beat icon-only
  app-bar buttons / menu / back / cart-icon). So on a product screen it reaches
  **add-to-cart** before the hamburger menu. Reveal-scroll only runs when a
  scrollable container exists (`Element.scrollable`, new) and each scroll changes
  the *observable* UI (raw activity+hierarchy via `recovery._screen_signature`); a
  scroll position is never captured as a screen; candidates de-dupe by a
  scroll-stable element **signature** (id/class/text/desc); and the backtracking
  invariant is explicit — after exploring a child it returns to the parent
  (verified in-app on the parent fingerprint) before the next candidate.
- **Engine harness** (`tools/harness.py`, `tools/perf.py`, `tests/test_performance.py`,
  new) — `py tools/harness.py` runs correctness + **complexity guards** and prints
  a report (exits non-zero on failure). Asserts *scaling ratios*, not wall-clock,
  so they hold on any machine: the hierarchy memo is **O(1)** reads within a screen
  state (20 reads → 1 dump), `parse_elements` / `rank_candidates` /
  `structural_fingerprint` are **O(n)**, the crawl's device I/O is **bounded**, and
  a FakeDevice run passes end to end. The same checks run in the test suite.
- **Failure classification & structured evidence** — a failed assertion is now a
  readable **defect report**, not a bare FAIL. `FailureReason.ASSERTION_FAILED`
  ("expected behaviour not observed" — a *neutral* engine fact); the validator
  attaches first-class **`expected` / `actual` / `observed_texts`** (on-screen
  evidence, ordering-only, never deciding the verdict); the runner sets the
  `failure_reason` and a `screen_summary` from the **post-condition** observation
  (the failure state). `report.py` renders an Expected/Actual/Observed block and a
  presentational tag — **"Likely defect"** for `ASSERTION_FAILED`, **"Couldn't
  reach target"** for BLOCKED, "App crashed", "Environment/device error" — so a
  bug reads differently from an unreachable target. Terminal diagnostics show the
  same. New scenario `testcases/sauce_problem_user_bug.yaml` (SwagLabs
  `problem_user`, a real buggy account) drives this to a flagged failure.
- **Auto-crawl** (`engine/crawler.py`, new) — bounded, deterministic screen
  discovery that **reuses the runner's own perception (`observe` + fingerprint)
  and the `Device` action seam** — not a second engine. Captures up to
  `max_screens` (1–5, hard-capped) new screens into the library. Safeguards by
  construction: `max_depth` + total-tap budget, visited-fingerprint dedup, a
  **destructive denylist** (never taps logout/delete/pay/…; skips are reported),
  an **app-scope guard** (a tap that leaves the package is undone with Back), and
  read-only fields (never types). **Starts from the screen already open** by
  default (`launch=False`) — drive to checkout, crawl the checkout flow — or
  `launch=True` to relaunch first. Surfaced as `cli.py crawl --package … --max-
  screens N [--launch]` and `POST /api/crawl`; a panel dropdown (1–5) + "launch
  app first" checkbox. A root-safe walk (no Back after a non-navigating tap; stop
  on leaving the app) fixes an escape-to-launcher bug.
- **Screen checkpoints** — a captured screen can be marked as a crawl **starting
  point** (`is_checkpoint`). `ScreenLibrary.set_checkpoint(id)`; `add(…,
  checkpoint=True)`; the crawler auto-marks the screen it started on and returns
  it as `summary["checkpoint"]`. Panel: a **📍 Set checkpoint** capture button, a
  per-row Set/Unset 📍 toggle (`POST /api/screens/checkpoint`), and a 📍 marker in
  the table.
- **Hierarchy memo** (`engine/device.py`, `engine/config.py`) — the live adapter
  memoizes `dump_hierarchy()`/`current_activity()` within one screen state
  (`config.HIERARCHY_CACHE`, default on). Every mutating action (tap/type/scroll/
  back/launch, and element click/set_text via an owner ref) calls `invalidate()`;
  `settle()` and recovery loops force-fresh so they still detect change. Measured
  live on `sauce_vague.yaml`: **23 → 6 device dumps (74% fewer), 51s → 29s**.
- **Screen library** (`engine/screen_library.py`, new) — `ScreenLibrary(package)`
  persists to `screens/<pkg>/library.json`; the user captures the screens they'll
  test by driving the app (`inspect --into-library`). `match(fingerprint)` finds
  a captured screen; `find_bearing(query)` locates an off-screen target's captured
  position so recovery scrolls *toward* it instead of blindly. Reuses the
  `cmd_inspect` bundle shape and `rank_candidates`.
- **CLI**: `inspect --into-library` (capture), `screens --package …` (list the
  library), `--preflight --test …` (match a test's targets to captured screens,
  no device), and `web [--port]` (launch the panel).
- **Web control panel** (`webapp/server.py` + `webapp/index.html`, new) — stdlib
  `http.server` exposing `env / testcases / screens / reports / inspect / run`;
  a static dark-theme page to capture screens, run tests, and open reports
  inline. Report file serving is path-escape guarded.
- **Full self-serve panel** (follow-up) — the panel now drives the whole loop
  with no terminal beyond starting the server: **start/stop the emulator**
  (`POST /api/emulator`, AVD picker from `GET /api/avds`), **launch an app** to
  its home screen for capture (`POST /api/launch`), **preflight** a test against
  the library (`GET /api/preflight`), **install an APK before a run** (picker
  from `GET /api/apks`), and **per-step diagnostics inline** after a non-PASS run
  (the same data as the terminal). `start-web.bat` boots the server and opens the
  page in one double-click. Full walkthrough in `docs/WEB_PANEL_GUIDE.md`.
- **Immutable screen identity + library editing** (follow-up) — every captured
  screen is now a record with an **immutable id** (`scr_…`); the label is
  human-facing only. `ScreenLibrary` gained `get`/`remove`/`rename` (all **by
  id**, so a duplicate or renamed label can never delete the wrong capture),
  `duplicates()` (fingerprints shared by >1 record — a hint, never a validity
  judgement), and a migration that backfills ids onto legacy entries. Records
  carry `package`, `activity`, `structural`/`content` fingerprints, `captured_at`
  and the screenshot. The web Screens panel shows **thumbnails**, a fingerprint
  column, a captured counter, inline capture feedback, a duplicate flag, and
  per-row **Rename / Remove**; screenshots are served through a path-escape
  guarded `/screens/` route (`screens/<pkg>/shots/<id>.png`). Reports open in a
  **new tab**. No engine hot-path change — capture correctness and editing are
  all outside the runner.
- **Run diagnostics** (`cli.py`) — a non-PASS run now prints each blocked/failed
  step's `failure_reason`, the screen it was on, and the nearest ranked on-screen
  matches (was only in `timeline.json`).
- **Clickable-ancestor promotion** (`engine/inspect.py`) — a tap target whose
  matching label sits on a non-clickable node (e.g. a product title) now promotes
  to its clickable card ancestor via `parent_index`, so `tap "Backpack"` resolves.
- **Tests** (86 total): `test_screen_library`, `test_device_cache`, `test_webapp`.

### Changed

- `engine/resolver.py` / `engine/recovery.py` / `engine/executor.py` /
  `engine/runner.py` thread the `ScreenLibrary` through; recovery records a
  bearing when the library knows an off-screen target; resolver records
  `role_rejected` candidates for clearer diagnostics.

### Validated

- **86 unit tests green** (`test_device_cache`, `test_screen_library`,
  `test_webapp` added).
- **Live on the `qa_test` emulator (SwagLabs, `com.swaglabsmobileapp`):**
  - `sauce.yaml` **PASS 6/6**, `sauce_negative.yaml` **PASS 6/6**,
    `sauce_vague.yaml` **PASS 6/6**.
  - `sauce_add_to_cart.yaml` **PASS 14/14** — the flow that was `BLOCKED`
    before this round (product title non-clickable + add-to-cart off-screen);
    now resolved by clickable-ancestor promotion and directed scroll.
- **Screen library** captured by driving the app: `login`, `catalog`, `product`
  (3 entries, distinct structural fingerprints under one `.MainActivity`, proving
  match is by fingerprint not by label). `screens` lists them; `--preflight`
  matched **all 4** `sauce_add_to_cart` targets to captured screens with **no
  device**, including the off-screen `add to cart` bearing — "All targets known."
- **Web panel** (`web --port 8765`): env, live screen-library table, 9 test
  cases, inline reports all served; report path-traversal returns 404.

## [Unreleased] — Perception-first engine (Phases 1–6)

Reworked the runner from a fixed "resolve selector → tap" pipeline into a shared
**Perception → Resolution → Action → Observation → Validation** engine. One
`Observation` object per screen is produced once and consumed by execution,
recovery, validation, and inspection alike. YAML now expresses *intent* (visible
labels), and the engine fetches, binds, and caches the real `resource-id`s
automatically — no manual id editing.

### Added

- **Perception layer** (`engine/inspect.py`, new)
  - `Element` dataclass: `resource_id`, `text`, `content_desc`, `cls`,
    `clickable`, `long_clickable`, `checkable`, `editable` (class endswith
    `EditText`), `password`, `focused`, `enabled`, `selected`, `bounds/center`,
    `index`, `depth`; helpers `.label()`, `.kind()` (field/button/view),
    `.interesting()`, `.center()`.
  - `parse_elements(hierarchy_xml)` — tolerant tree walk (returns `[]` on
    malformed XML instead of raising).
  - `structural_fingerprint(activity, elements)` — sha1 of activity + sorted
    `id:class:desc` (excludes text, so a screen keeps identity across data).
  - `content_fingerprint(...)` — structural + text, for change detection.
  - `window_flags(elements)` — dialog/popup detection.
  - `ScreenDiff` + `screen_diff(before, after)` → `NAVIGATION_DETECTED` /
    `SCREEN_CHANGED` / `CONTENT_CHANGED` / `KEYBOARD_TOGGLED` / `NO_CHANGE`.
  - `Candidate` (with `base` and `score`) + `rank_candidates(query, elements,
    role, limit=5)` — difflib similarity over text/desc/id-tail, with role
    bonuses (editable for fields, clickable for taps) applied to `score` only.
  - `format_table(elements)` for the inspect view.

- **Self-healing selector cache** (`engine/selector_cache.py`, new)
  - `SelectorCache(package)` persists to `.selector-cache/<package>.json`.
  - Key = `structural_fingerprint | role | normalized_query`. Learns a concrete
    binding on first resolve; reuses it on later runs; a stale binding falls
    through to re-ranking instead of failing.

- **Semantic actions** (`engine/executor.py`, `engine/loader.py`)
  - String targets: `target: "Login"` → intent label.
  - `enter_text` (type into a field found by label) and `submit` (find and tap a
    common submit control, or an explicit target).
  - Keyboard auto-dismiss before tap/submit, so the IME action key can't hijack
    ranking and the button isn't obscured.

- **Richer validation** (`engine/validator.py`)
  - `not_visible` (inverse of `text_exists`) and `activity_changed` asserts,
    reasoning over the preceding action's before/after observation.

- **Failure taxonomy** (`engine/models.py`)
  - `FailureReason`: `TARGET_NOT_FOUND`, `TARGET_AMBIGUOUS`, `TARGET_DISABLED`,
    `TARGET_NOT_CLICKABLE`, `UNEXPECTED_SCREEN`, `RECOVERY_FAILED`,
    `DEVICE_ERROR`, `APP_CRASHED`, `TIMEOUT`. A blocked step now reports the
    reason plus ranked on-screen suggestions instead of a bare `BLOCKED`.

- **CLI subcommands** (`cli.py`)
  - `inspect` — dump the live screen (elements table, fingerprints, window
    flags) with `--label` probing and `--launch`; no test file needed.
  - `replay` — re-print a run's verdicts from `reports/<run>/timeline.json`
    with `--from-report`; no device needed.
  - `doctor` — environment check.

- **Evidence**: `evidence.write_bindings()` writes
  `reports/<run>/bindings.json` — the label→concrete-selector map the run
  learned.

- **Tests** (73 passing): `test_inspect`, `test_locator`, `test_semantic`,
  `test_validation_extra`, `test_recovery_dialog`, `test_cli_replay`.

- **Test cases**: `testcases/shop_login_semantic.yaml` — fully semantic login,
  zero resource-ids; plus `login_invalid.yaml`, `nextcloud_login.yaml`,
  `aimring_login.{txt,yaml}`.

- **Docs**: `docs/TEST_GUIDE.md` §9b (semantic targets, auto-binding, inspect &
  replay); full HTML project guide `docs/index.html`.

### Changed

- **`engine/models.py`** — `Observation` grew lazy `elements()`,
  `structural_fingerprint()`, `content_fingerprint()`, `window()` (imports
  `inspect` lazily to avoid a cycle). `ResolutionResult` grew
  `status`/`candidates`/`reasons`/`bound_selector` + `as_dict`. `ActionResult`
  grew `failure_reason`/`suggestions`/`screen_summary` + `as_dict`. Added
  `STRATEGY_RANKED` and `RESOLVE_EXACT/MATCHED/AMBIGUOUS/NOT_FOUND`.
- **`engine/resolver.py`** — `resolve()` order is now selectors (EXACT) → cache
  fast-path (self-healing) → candidate ranking (MATCHED/AMBIGUOUS) → OCR.
  Acceptance gates on `base >= RESOLVE_MIN_SCORE` **and** role fitness, so a
  strong text match on a wrong-role element (e.g. a "Sign in" heading) is
  rejected in favour of the real control.
- **`engine/recovery.py`** — `reach()` threads `role`/`cache`; added a
  dialog-dismissal stage (Allow / While using the app / …) driven by
  `inspect.window_flags`; recovery now detects unchanged screens and stops
  redundant retries and no-op scroll passes.
- **`engine/runner.py`** — builds a `SelectorCache(package)`, passes it through
  execution, saves it, and writes `bindings.json`; `activity_changed` added to
  the trailing-assert set.
- **`engine/config.py`** — `RESOLVE_MIN_SCORE=0.60`, `RESOLVE_AMBIGUOUS_GAP=0.10`,
  `SETTLE_REQUIRE_SCREEN_STABLE`, `SETTLE_SCREEN_EPSILON`,
  `OCR_BACKEND="tesseract"`.
- **`.gitignore`** — ignore `apks/`, `sample-app/build/`, `manual-demo/`,
  `screens/`, `.selector-cache/`.

### Fixed

- Rank bonus could push a weak match over threshold — separated `base` (accept)
  from `score` (order).
- Product titles and other visible labels could be non-clickable while their
  card/container was clickable — hierarchy parent links now let ranked tap
  targets promote matching labels to clickable ancestors.
- Non-clickable "Sign in" title matched `submit` before the real Login button —
  added the role gate.
- Semantic login failed when the keyboard's IME key matched `submit` and the
  keyboard obscured the button — added keyboard auto-dismiss.
- Recovery could appear stuck while retrying an unchanged screen, and settle
  timeouts were silent — redundant recovery work is skipped and action details
  record a screen settle timeout.
- `device.py` logcat `cp1252` `UnicodeDecodeError` — decode `utf-8`,
  `errors="replace"`.

### Validated

- 75 unit tests green.
- Live semantic no-id login (`shop_login_semantic.yaml`) **PASS 6/6** on the
  `qa_test` emulator; `bindings.json` proves auto-binding
  (`email`→`…:id/email`, `password`→`…:id/password`, `log in`→`…:id/login`).
- Inspector validated 10/10 against ground-truth ids on the sample app and
  Nextcloud.

### Known limitations

- `app_aimring_v0.1.3.apk` is an AAB base split — `INSTALL_FAILED_MISSING_SPLIT`
  on a plain install. Needs a universal APK or the full split set to run its
  own flow live.
