# Changelog

All notable changes to the mobile-testing engine are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — Speed, screen library, web panel

Follow-up round: make runs fast, add a pre-fetched screen library, and a local
web control panel. Builds on the perception-first engine below.

### Added

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
