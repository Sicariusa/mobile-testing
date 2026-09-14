# Mobile QA Test Runner

An Android UI test runner in Python. Given an APK and a structured test case
(YAML), it installs and launches the app, executes each step automatically
(tap / type / swipe / launch), and **validates every expected outcome with a
deterministic algorithm** that perceives the screen two ways:

- the **UI hierarchy** (accessibility tree) — fast and exact, and
- **screenshot + OCR** — for text the hierarchy never exposes.

When a target is not immediately reachable it **recovers** (wait/retry, dismiss
a blocking keyboard, scroll into view, then OCR) before giving up. Every step
produces evidence (before/after screenshots, hierarchy dump, recovery trace,
OCR matches) and the run produces a self-contained **HTML report**.

```
python cli.py --apk app.apk --test testcases/login.yaml
```

---

## Quickstart

```bash
# 1. install Python deps
pip install -r requirements.txt

# 2. install the native tools (see docs/SETUP_ANDROID.md for details)
#    - tesseract  (OCR)
#    - adb, aapt  (Android platform-tools + build-tools)

# 3. check what's ready
python cli.py --check-env

# 4. with a device/emulator connected, run a test case
python cli.py --apk app.apk --test testcases/login.yaml
```

`--check-env` diagnoses tooling and whether a live run is possible — it never
throws:

```
Mobile QA Environment
────────────────────────────────────────────────
  python         ✓ FOUND    (required)  3.11.x
  adb            ✓ FOUND    (required for live run)  /usr/bin/adb
  aapt           ✓ FOUND    (required for live run)  /usr/bin/aapt
  tesseract      ✓ FOUND    (required)  /usr/bin/tesseract
  uiautomator2   ✓ FOUND    (required for live run)
  device         ✗ MISSING  (required for live run)  no Android target detected
────────────────────────────────────────────────
  Core tests:  READY
  Live runner: BLOCKED
               → connect an emulator or physical device (see docs/SETUP_ANDROID.md).
```

---

## Running against a real device

A live run needs a real Android target. It **cannot run in a cloud container
without hardware virtualization** (an emulator needs KVM). On a machine that
has a device or an AVD:

1. Follow **[docs/SETUP_ANDROID.md](docs/SETUP_ANDROID.md)** to install the SDK,
   connect a device or start an emulator, and initialise uiautomator2.
2. `python cli.py --check-env` should show **Live runner: READY**.
3. `python cli.py --apk app.apk --test testcases/login.yaml`.

The console prints the overall **PASS/FAIL** and the path to
`reports/<run_id>/report.html`.

---

## The test case (YAML)

Selectors and expected values are supplied by the test author. `{{email}}`
style placeholders are filled from `data`.

```yaml
name: "Login with valid credentials"
package: com.example.shop
launch_activity: null
data:
  email: test@example.com
  password: Password123
steps:
  - action: launch
  - action: tap
    target: { text: "Login" }
  - action: type
    target: { id: "com.example.shop:id/email" }
    value: "{{email}}"
  - action: tap
    target: { text: "Login" }
  - assert:
      type: text_exists      # hierarchy first, then OCR automatically
      value: "Welcome"
  - assert:
      type: ocr_text_exists  # OCR only — text the tree never exposes
      value: "PAY NOW"
  - assert:
      type: screen_changed   # evidence a state transition occurred
```

**Target selector priority:** `id` → `text` (exact, then contains) → `desc` →
`ocr: "text"` (find the label on the screenshot and tap its center) when
selectors can't reach it.

**Assertion types:** `text_exists`, `ocr_text_exists`, `element_exists`,
`activity_is`, `screen_changed`.

---

## How validation works (deterministic, fixed order)

1. **Crash gate** — a fatal in logcat since launch ⇒ `CRASH`, always checked first.
2. **Per-assertion** logic:
   - `text_exists` → hierarchy, then OCR, else FAIL
   - `ocr_text_exists` → OCR only
   - `element_exists` → hierarchy
   - `activity_is` → current activity
   - `screen_changed` → before/after differ by ≥ threshold
3. `screen_changed` is the **only** assertion validated by change detection, and
   it means *a state transition happened* — never semantic proof that some other
   expectation was met. (Tapping Login and hitting an error screen changes the
   screen but is not a successful login.)

Thresholds (`OCR_MIN_CONFIDENCE`, `CHANGE_MIN`, retry/scroll bounds, settle
timings) all live in one place: [`engine/config.py`](engine/config.py).

---

## Output

```
reports/<run_id>/
  report.html          # open this
  timeline.json        # the whole run, machine-readable
  logcat.txt
  steps/<n>/
    before.png  after.png  hierarchy.xml  step.json
```

Each step records `resolved_by` (how the target was found, with confidence) and
`validated_by` (how the outcome was confirmed) — the most useful debugging
telemetry the engine produces.

---

## Development & tests

The engine reaches the device only through the `Device` interface
([`engine/device.py`](engine/device.py)), so the entire core is tested against a
`FakeDevice` with **no Android required**. Screenshots in tests are rendered
from real text so OCR runs for real.

```bash
pytest -q
```

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for a full walkthrough of
the layers, data models, and how to add a new action or assertion type.

---

## Requirements

- Python 3.11+
- `tesseract` on PATH (OCR)
- For live runs: `adb` + `aapt` (Android SDK), `uiautomator2`, and a connected
  device or running AVD.
