# Build Plan: Mobile QA Test Runner

## Context

`sicariusa/mobile-testing` is an empty repo. We are building an Android UI
test runner in Python from the supplied build brief: given an APK + a YAML
test case, it installs/launches the app, executes each step (tap/type/swipe),
perceives the screen two ways (UI hierarchy + screenshot/OCR), recovers when a
target isn't reachable, validates each expected outcome with a deterministic
algorithm (hierarchy → OCR → change detection), and emits per-step evidence +
an HTML report.

### Hard environment constraint (drives verification strategy)
This container **cannot run an Android emulator**: no `/dev/kvm`, zero CPU
virtualization flags, and `dl.google.com` is blocked by the proxy so the
Google SDK/system images can't be downloaded. No physical device is attached.
`adb`/`aapt`/`tesseract` and all Python deps **are** installable (apt + PyPI).

**Decision (confirmed with user):** Build the full codebase and install every
dependency now. Verify the entire device-independent core with unit tests
against a **FakeDevice** + screen fixtures. The live
`python cli.py --apk app.apk --test login.yaml` run against a real app is
deferred to a machine/device with a real Android target. The code is written
so that run works unchanged there.

## Deliverable layout (`mobile-qa/`)

Matches the brief's structure exactly:
```
mobile-qa/
  engine/{__init__,models,device,observation,ocr,resolver,recovery,
          executor,validator,stabilize,evidence,report,loader,runner}.py
  testcases/login.yaml
  reports/            (gitignored)
  tests/              (unit tests + FakeDevice + fixtures)
  cli.py
  requirements.txt
  README.md
  .gitignore
```

## Design decisions

- **`models.py` (build first).** `Observation`, `ResolutionResult`,
  `RecoveryTrace`, `ActionResult` as `@dataclass`es with an `as_dict()`/JSON
  helper (drives `timeline.json` + report). Status enum: PASS/FAIL/BLOCKED/
  CRASH/SKIPPED. This is the shared currency between all modules.
  - **`Observation` = a concrete point in time:** `timestamp`, `package`,
    `activity`, `screenshot_path`, `hierarchy_xml`, `keyboard_visible`. Add a
    pure `transition(before, after)` helper deriving `activity_changed`,
    `hierarchy_changed`, `screen_changed`, `new_text`/`removed_text` — the
    substrate for later autonomous state-transition reasoning.
  - **`resolved_by` and `validated_by` are first-class metadata**, each with
    `confidence` (1.0 for selector hits, OCR score for OCR). `ActionResult`
    always records how the target was found (e.g. `ocr @0.94` vs
    `resource_id @1.0`) and how the outcome was validated, plus
    `recovery_attempts` and, on CRASH, a `crash_signature` (the FATAL line).
    These are treated as primary outputs, not incidental fields.
- **`config.py` / one thresholds spot.** `OCR_MIN_CONFIDENCE`, `CHANGE_MIN`,
  settle timings, retry/scroll bounds in a single module so they're tunable.
- **Device abstraction.** `device.py` wraps `uiautomator2` + `adb`
  (`read_apk_metadata` via `aapt dump badging`). All engine modules reach the
  device **only** through this layer, so `tests/FakeDevice` can substitute a
  scripted device that returns fixture hierarchies/screenshots. This is what
  makes the core verifiable without hardware.
- **`observation.py`** `observe(d) -> Observation` — one before/after per step.
- **`ocr.py`** `ocr_find(image, text)` via `pytesseract.image_to_data`
  (word/line boxes), normalized case-insensitive matching, returns
  bounds+confidence; `ocr_text_exists(image, text) -> (bool, conf)`.
- **`resolver.py`** selector priority `id → text_exact → text_contains → desc
  → ocr`; records every attempt; `find_with_scroll(max_scrolls=3)`.
- **`recovery.py`** `reach(d, target)`: bounded wait/retry → dismiss keyboard →
  scroll → OCR; full `RecoveryTrace`; returns `None` → BLOCKED.
- **`stabilize.py`** `settle()`: stable when two hierarchy dumps ~300ms apart
  match AND activity unchanged, or timeout. Callers stable for later upgrades.
- **`validator.py`** crash gate first, then **per-assertion** logic — change
  detection is NOT a generic fallback that can turn any assertion into PASS
  (that would false-positive when a tap causes an error screen). Explicit map:
  - `text_exists`: hierarchy → PASS(`validated_by=hierarchy`); else OCR ≥
    `OCR_MIN_CONFIDENCE` → PASS(`ocr`); else FAIL.
  - `ocr_text_exists`: OCR only → PASS(`ocr`)/FAIL.
  - `element_exists`: resolver hit → PASS(`hierarchy`)/FAIL.
  - `activity_is`: activity match → PASS(`hierarchy`)/FAIL.
  - `screen_changed`: `change_ratio(before,after) ≥ CHANGE_MIN` →
    PASS(`change`)/FAIL. **`change` = evidence of a state transition, never
    semantic proof of another assertion.**
  `change_ratio` = normalized hierarchy diff and/or screenshot pixel-diff ratio.
- **`executor.py`** runs the section-6 loop for actions → `ActionResult`.
- **`evidence.py`** writes `reports/<run_id>/steps/<n>/{before,after}.png`,
  `hierarchy.xml`, recovery trace + OCR matches (JSON); maintains
  `logcat.txt`, `timeline.json`.
- **`report.py`** single self-contained `report.html` (inline CSS/JS):
  per-step action, color-coded result, `resolved_by`, `validated_by`,
  recovery attempts, OCR matches, before/after thumbnails.
- **`runner.py`** load+validate YAML → boot/connect → install → iterate steps →
  stop on CRASH/BLOCKED (rest SKIPPED) → write timeline+report → overall result.
- **`cli.py`** `python cli.py --apk app.apk --test testcases/login.yaml`;
  prints overall PASS/FAIL + report path; precise setup message if adb/aapt/
  tesseract/device missing.

## Build order (4 layers — fail-isolation maps to a layer)

- **Layer 1 — Foundation:** `models.py`, `config.py`, `device.py` (real
  u2/adb), `FakeDevice` (tests), `.gitignore`, `requirements.txt`.
- **Layer 2 — Perception:** `observation.py`, `ocr.py`, `resolver.py`,
  `stabilize.py`, `recovery.py`.
- **Layer 3 — Execution:** `validator.py`, `executor.py`, `runner.py`.
- **Layer 4 — Evidence & surface:** `evidence.py`, `report.py`, `loader.py`,
  `cli.py`, `testcases/login.yaml`, `README.md` + `docs/`.

Debug map: can't connect→Device; can't see UI→Observation; can't find
button→Resolver/OCR; can't recover→Recovery; action no-op→Executor; wrong
result→Validator; report broken→Evidence/Report.

## `--check-env` (capability diagnosis, not an exception)

`cli.py --check-env` prints a clean table probing `python`, `adb`, `aapt`,
`aapt2`, `tesseract`, `emulator`, `uiautomator2`, and a connected device — each
labeled FOUND / MISSING / OPTIONAL / REQUIRED-FOR-LIVE-RUN — then a rollup:
`Core tests: READY` and `Live runner: READY|BLOCKED (connect a device)`.
Package-name assumptions are not hard-coded (aapt **or** aapt2 satisfies aapt).

## Install step (this session)

- `apt-get install -y tesseract-ocr adb aapt` (aapt via android build-tools
  pkg; fall back to `aapt2`/`google-android-build-tools` if needed).
- `pip install -r requirements.txt` (uiautomator2, pytesseract, Pillow,
  pyyaml, plus pytest for tests).
- Document any package that couldn't be fetched, with the exact remediation.

## Verification (what actually proves it works here)

Deterministic, extensive tests under `tests/` using `FakeDevice` + named
fixture scenarios (`login_initial.xml`, `login_keyboard.png`,
`login_scrolled.xml`, `login_success.xml`, `login_crash.xml`, …). Tests assert
the **reasoning metadata**, not just the status:
- **validator**: crash gate fires first (→ CRASH + `crash_signature`);
  hierarchy hit → PASS/`validated_by=hierarchy`; OCR-only `text_exists`
  (hierarchy lacks it, OCR finds it) → PASS/`ocr`; `screen_changed` above/below
  `CHANGE_MIN` → PASS/FAIL `change`; **error-screen-after-tap does NOT pass a
  `text_exists` for the success string** (guards the false-positive the review
  flagged); nothing-satisfied → FAIL.
- **ocr**: `ocr_find`/`ocr_text_exists` on a generated fixture image with known
  text → correct bounds + hit/miss (real tesseract, no device).
- **change_ratio**: identical vs. clearly-different hierarchy/screenshot pairs.
- **resolver/recovery**: off-screen target found via scroll (asserts
  `resolved_by=ocr` when selectors miss, with confidence); keyboard-obstruction
  scenario; absent target exhausts retries/scroll/OCR → BLOCKED with full
  `recovery_attempts` trace.
- **loader**: valid YAML parses; `{{data}}` interpolation; bad schema rejected.
- **report**: renders HTML from a synthetic timeline; asserts key markers
  (color, `resolved_by`, `validated_by`, recovery, OCR matches).
- **runner (mocked)**: full `login.yaml` through FakeDevice end-to-end — the
  scenarios (normal / keyboard obstruction / off-screen / missing / OCR-only /
  transition / crash) assert exact `(status, resolved_by, validated_by)` tuples
  and write a real openable `reports/<run_id>/report.html`.

Run: `pytest -q` (all green) + open the generated sample report.
Also `python cli.py --help` and a `--check-env` path that prints the precise
"install X / connect a device" guidance, proving the real-device entrypoint is
wired (it will report the missing device here, by design).

## Documentation (first-class deliverable)

A `docs/` directory plus README, so the project can be picked up later:

- **`docs/SETUP_ANDROID.md` — install & connect an Android device (for later).**
  Step-by-step, copy-pasteable, covering:
  - Install Android SDK command-line tools; set `ANDROID_HOME`/`PATH`;
    `sdkmanager` install of `platform-tools` (adb), `build-tools` (aapt),
    `emulator`, and a `system-images` package.
  - **Emulator path:** create an AVD with `avdmanager`, launch headless
    (`emulator -avd <name> -no-window -no-audio`), and the KVM/virtualization
    requirement (why it won't run in this cloud container, what a host needs).
  - **Physical device path:** enable Developer Options + USB debugging,
    `adb devices`, authorize the host, `adb connect host:port` for wireless/
    remote.
  - **uiautomator2 init** (`python -m uiautomator2 init`) and the ATX agent.
  - Install tesseract per-OS; verify `tesseract --version`.
  - A troubleshooting table (no device, unauthorized, offline, no aapt, OCR
    empty) and a one-command `python cli.py --check-env` to self-diagnose.
- **`docs/ARCHITECTURE.md` — understand the codebase (for later).**
  The layered diagram (device → observation → engine → evidence/report), the
  four shared data models and how they flow between modules, the executor loop
  and the fixed-order validation algorithm walked through step by step, where
  the tunable thresholds live, and a module-by-module responsibility map with
  file pointers. Includes "where to start reading" and "how to add a new
  action/assert type" extension notes.
- **`README.md`** — quickstart, the confirmed cloud-container limitation, the
  real-device run command, and links into `docs/`. Points here first.

## Out of scope / deferred
- Live emulator run in this container (impossible — no KVM). README documents
  how to run it on a real device/AVD.
- EasyOCR upgrade path, animation/network settle signals — left as noted hooks.

## Git
- Work on branch `claude/mobile-qa-test-runner-qfa1el`, commit in logical
  chunks, push with `-u origin`. No PR unless asked.

---

## As-built status (built + pushed in the cloud session)

Everything in this plan was implemented, committed, and pushed to
`claude/mobile-qa-test-runner-qfa1el`. Honest split of what is proven vs. what a
local session still needs to validate:

### Verified here (executed)
- `pytest -q` → **30 passed**. Real Tesseract runs against rendered screenshots.
- Coverage: OCR find/exists; validator (crash gate first, hierarchy→OCR,
  OCR-only pass, the error-screen false-positive guard, `screen_changed`
  thresholds, `element_exists`, `activity_is`); resolver (selector priority +
  OCR fallback + scroll); recovery (keyboard/scroll/BLOCKED escalation); loader
  (schema + `{{data}}` + parses `testcases/login.yaml`); report HTML markers;
  runner end-to-end across normal / OCR-only / blocked / crash asserting exact
  `(status, resolved_by, validated_by)` tuples.
- `python cli.py --check-env` and `--help`; a real `report.html` was generated.
- Installed and importable: `adb`, `aapt`, `tesseract`, `uiautomator2`,
  `pytesseract`, `Pillow`, `pyyaml`.

### NOT verified here — validate on your LOCAL run (no device/APK in the cloud box)
The device-independent core is tested; the **live-device adapter is written to
the uiautomator2 v3 / adb API but never ran against real hardware**. First live
run is where any API mismatch would surface. Check specifically:
- `engine/device.py::AndroidDevice` — `connect`, `install`, `launch`
  (`app_start`), `screenshot`, `dump_hierarchy`, `app_current`,
  `keyboard_visible` (dumpsys `mInputShown`), `find` (u2 selectors),
  `set_text`/`send_keys`, `scroll_forward`, `press_back`, `swipe`.
- `engine/device.py::read_apk_metadata` — `aapt dump badging` regex against a
  real APK's output.
- The full path: `python cli.py --apk app.apk --test testcases/login.yaml`.

### Local bring-up checklist
1. `pip install -r requirements.txt`
2. Follow `docs/SETUP_ANDROID.md` (SDK + device/AVD + `python -m uiautomator2 init`).
3. `python cli.py --check-env` → expect **Live runner: READY**.
4. Point `testcases/login.yaml` at a real app: set `package`, the resource-ids,
   and expected text/values to your app's actual values.
5. `python cli.py --apk <your.apk> --test testcases/login.yaml`, then open
   `reports/<run_id>/report.html`.
6. If a u2/adb call errors, fix it in `engine/device.py` only — the layers above
   it are covered by tests and should not need changes.
