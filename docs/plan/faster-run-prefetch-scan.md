# Plan — Faster runs, a pre-fetched screen library, and a web control panel

## Context

Runs got noticeably slower once the perception-first engine landed. Root cause:
every step issues many **`dump_hierarchy()`** calls (each a slow adb uiautomator
dump, ~0.5–2 s on the emulator), because `resolve()` re-dumps the screen the
executor *just* observed, `settle()` polls with more dumps, and `recovery.reach`
re-resolves **and** now calls `_screen_signature()` (another dump) on every
retry/scroll. A best-case action is ~5 dumps; a step that enters recovery (e.g.
`tap "Backpack"` on SwagLabs) is 20+.

Two functional gaps showed up in the same test:
- The product **title** is non-clickable while its card is clickable with no
  label — already fixed by the reviewed working-tree change (parent-index +
  `clickable_ancestor` promotion in `engine/inspect.py`, plus `role_rejected`
  recording in `engine/resolver.py`). Keep it.
- Test steps don't mention everything (the **add-to-cart** button needed a
  scroll). The engine should not depend only on the literal steps.

Goal, in the user's chosen order: **(1) make runs fast** by removing redundant
dumps; **(2) pre-fetch a screen library** the user captures by driving the app,
then match it at runtime so most live dumps disappear and off-screen targets are
reached deliberately; **(3) wrap it in a simple web control panel** (static HTML
+ a tiny local Python server over the existing engine).

The reviewed working-tree changes (clickable-ancestor fix, recovery no-progress
break, `cli.py` `_print_diagnostics`, the three `sauce_*.yaml` cases) are sound
and stay; this plan builds on them.

---

## Stage 1 — Speed: one observation per screen state (no redundant dumps)

Thread the observation the executor already has into resolution/recovery, and
memoize the raw hierarchy at the device seam so within one screen state every
consumer reuses a single dump.

- **`engine/device.py`** — add a tiny hierarchy memo on the live adapter:
  `dump_hierarchy()` caches its last XML and returns it until invalidated;
  `invalidate()` clears it. Any mutating call (`tap_xy`/element click via
  `find`+act path, `input_text`, `press_back`, `scroll_forward`, `swipe`,
  `launch`) calls `invalidate()`. `current_activity()` gets the same short memo.
  FakeDevice keeps its current behavior (already cheap) but gains a no-op
  `invalidate()` so the interface matches.
- **`engine/resolver.py`** — `resolve(...)` takes an optional
  `screen: tuple[str, list]` (fingerprint, elements). When given, skip
  `_screen(d)` and reuse it. `find_with_scroll`/recovery pass fresh screens only
  after they actually scroll.
- **`engine/executor.py`** — build the screen once from `before` (it already
  calls `observe(before)`; reuse `before.structural_fingerprint()` +
  `before.elements()`) and pass it into `reach(...)`/`resolve(...)` for the first
  resolution attempt.
- **`engine/recovery.py`** — replace the extra `_screen_signature()` dumps with
  the hierarchy the immediately-preceding `_resolve()` already fetched (via the
  memo), so the no-progress check costs zero extra dumps. Keep the early-break
  behavior.
- **`engine/config.py`** — add `HIERARCHY_CACHE` toggle (default on) and a small
  `SETTLE_TIMEOUT_S` review; `settle()` still needs real dumps (it detects
  change) but runs against the memo only across the poll boundary, not for
  callers.

Expected effect: best-case action drops from ~5 dumps to ~2 (before + after,
with settle reusing them); a recovering step drops from 20+ to a handful.

## Stage 2 — Pre-fetched screen library + runtime match

A reusable, per-app library of the screens the user chose to test, captured by
driving the app. At runtime the engine matches the current screen to a library
entry by **structural fingerprint** and resolves from the stored inventory,
dumping live only when the match is stale.

- **New `engine/screen_library.py`** — `ScreenLibrary(package)` persists to
  `screens/<package>/library.json`: a list of entries `{label, activity,
  structural_fingerprint, elements[], screenshot, captured_at}`. Methods:
  `add(observation, label)`, `match(fingerprint) -> entry|None`,
  `entries()`, `save()`. Reuses `inspect.parse_elements` /
  `structural_fingerprint` and the existing `observation.json` bundle shape from
  `cmd_inspect` (same fields — one writer).
- **`cli.py`** — extend inspect into a capture that appends to the library:
  `py cli.py inspect --label catalog --into-library` (writes the bundle *and*
  the library entry). Add `py cli.py screens --list` to print the library.
- **`engine/resolver.py`** — accept an optional `library`; before dumping live,
  if the current fingerprint matches a library entry, rank against the stored
  elements first (still verify the concrete selector exists before acting, so a
  moved element self-heals like the cache does today).
- **Off-screen targets ("unmentioned" steps).** When a target isn't on the
  current screen but the matched library entry (or an adjacent captured screen)
  contains it, recovery scrolls *with intent* toward its captured bounds instead
  of blind scroll passes — turning "add to cart needs a scroll" into a directed
  action. Implemented in `recovery.reach` using the library entry's element
  bounds; falls back to today's blind scroll when there's no library.
- **`engine/runner.py`** — construct `ScreenLibrary(package)` alongside the
  existing `SelectorCache`, pass both through `executor.execute`. Library is
  read-mostly at run time; the cache still learns.

This makes execution "not depend only on the steps": the library is the map, the
steps are the intent, and the resolver bridges them.

## Stage 3 — Web control panel (static HTML + tiny local server)

A single-page control panel over the engine. No new runtime deps — Python
stdlib `http.server`.

- **New `webapp/server.py`** — a stdlib `ThreadingHTTPServer` exposing JSON:
  `GET /api/devices`, `GET /api/env` (wraps `device_mod.probe_environment`),
  `POST /api/inspect` (drive-capture the current screen into the library),
  `GET /api/screens` (library list + screenshots), `GET /api/testcases`,
  `POST /api/run` (runs a test via `engine.runner.run`, streams status),
  `GET /api/reports` + serve `reports/<run>/report.html`. Each endpoint is a thin
  call into existing functions — no engine logic duplicated.
- **New `webapp/index.html`** — static page, dark theme matching
  `docs/index.html`: panels for **Device/env**, **Screens** (Capture-current
  button → grows the library, thumbnails + element counts), **Test cases**
  (pick/edit a YAML, dry-run, run), **Reports** (open the latest report inline).
  Plain `fetch()` to the endpoints; no framework, no build step.
- **`cli.py`** — `py cli.py web [--port 8765]` launches the server and prints the
  localhost URL. Read-only viewing works with no device; capture/run require a
  connected device, surfaced in the Device panel.

Scope now = the four panels above ("options for everything" incrementally); the
server is the seam so more options are added later without touching the engine.

---

## Files

- Modify: `engine/device.py`, `engine/resolver.py`, `engine/recovery.py`,
  `engine/executor.py`, `engine/runner.py`, `engine/config.py`, `cli.py`.
- New: `engine/screen_library.py`, `webapp/server.py`, `webapp/index.html`.
- Tests: extend `tests/test_locator.py` (screen-passed-in path, library match),
  `tests/test_resolver_recovery.py` (directed scroll, no-extra-dump), new
  `tests/test_screen_library.py`, `tests/test_webapp.py` (endpoints against a
  FakeDevice). Keep all current tests green.
- Reuse: `inspect.parse_elements` / `structural_fingerprint` / `rank_candidates`,
  `observation.observe`, `SelectorCache` (pattern for the library), the
  `cmd_inspect` bundle shape, `docs/index.html` styles for the web page.

## Verification

1. `py -m pytest -q` — all green (current + new).
2. Speed: `py cli.py --test testcases\sauce_vague.yaml` and compare wall-clock +
   count `dump_hierarchy` calls (temporary counter/log) before vs after Stage 1
   — expect a large drop, especially on any recovering step.
3. Pre-fetch: drive SwagLabs, capture `login` / `catalog` / `product` into the
   library; run `testcases\sauce_add_to_cart.yaml` — the earlier BLOCKED
   `tap "Backpack"` now resolves via the clickable-ancestor fix, and add-to-cart
   is reached by directed scroll; run passes end-to-end.
4. Web: `py cli.py web`, open `http://localhost:8765` — capture a screen, see it
   in the Screens panel, run a test, open its report inline.
5. Re-run the negative + vague cases to confirm no regression in failure
   reporting (the `_print_diagnostics` output still shows on non-PASS).