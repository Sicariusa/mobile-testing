# Test Guide — run and verify everything yourself

A top-to-bottom walkthrough: configure an APK → open the emulator → run the
login flow → validate → then every other flow (negative path, a real
open-source app, driving the device by hand) and how to read the evidence.
Commands are Windows PowerShell. Every run writes its own timestamped report to
`reports/<run_id>/report.html` — see [§9](#9-how-a-run-executes-and-where-it-is-saved).

---

## The 30-second mental model

```
APK + login.yaml
      │
      ▼
 cli.py ──▶ probe env ──▶ connect device ──▶ install APK ──▶ for each step:
                                                   observe(before)
                                                   act  (tap / type / swipe)   ← resolver: id→text→desc→OCR
                                                   settle
                                                   observe(after)
                                                   validate  ← hierarchy → OCR → change
                                                   write evidence (png + xml + json)
      │
      ▼
 reports/<run_id>/report.html   (per-step: resolved_by, validated_by, screenshots)
```

Nothing in the engine talks to Android except `engine/device.py`, which is why
the whole thing is unit-tested against a fake device with no hardware.

---

## 0. Prerequisites (already installed on this machine)

On the user `PATH` (open a NEW terminal so it is fresh):

| Tool | Where | Check |
|------|-------|-------|
| Android SDK | `C:\Android\sdk` (`ANDROID_HOME`) | — |
| adb | `platform-tools` | `adb version` |
| aapt | `build-tools\34.0.0` | `aapt version` |
| emulator + image | `emulator`, `system-images;android-34;google_apis;x86_64` | `emulator -version` |
| tesseract | `C:\Program Files\Tesseract-OCR` | `tesseract --version` |
| Python 3.12 + deps | `pip install -r requirements.txt` | `py -m pytest -q` |

If a tool is "not recognized", its folder is missing from `PATH` — reopen the
terminal, or see [SETUP_ANDROID.md](SETUP_ANDROID.md) to install from scratch.

> **Windows: use `py`, not `python`.** Bare `python` is often intercepted by the
> Microsoft Store alias ("Python was not found…"). This guide uses the `py`
> launcher, which resolves to your real Python 3.12. To make `python` work
> instead, disable the alias in Settings ▸ Apps ▸ Advanced app settings ▸ App
> execution aliases.

---

## 1. Configure the APK (what are we testing?)

The runner needs an APK and a `testcases/*.yaml` that names the app's
`package`, the launchable activity, and the selectors (resource-ids / text) for
each step. Two ways to get an APK:

**A. The bundled sample app** (deterministic, offline). Build it:

```powershell
.\sample-app\build.ps1      # aapt2 → javac → d8 → zipalign → apksigner
```

Produces `sample-app\build\shop-login.apk`. Inspect what it exposes:

```powershell
aapt dump badging sample-app\build\shop-login.apk | Select-String "package:|launchable-activity:"
# package: name='com.example.shop' ...
# launchable-activity: name='com.example.shop.MainActivity'
```

Those values are exactly what `testcases\login.yaml` uses (`package`,
resource-ids `com.example.shop:id/email` / `:id/password`, button text `Login`).

**B. A real open-source app.** Download from a trusted source (F-Droid), then
discover its real selectors by dumping the screen:

```powershell
# example: Nextcloud
adb -s emulator-5554 install -r -g apks\nextcloud.apk
aapt dump badging apks\nextcloud.apk | Select-String "package:|launchable-activity:"
adb -s emulator-5554 shell am start -n com.nextcloud.client/com.nmc.android.ui.LauncherActivity
adb -s emulator-5554 exec-out uiautomator dump /dev/tty   # read resource-ids/text
```

Put the discovered ids/text into a new `testcases\*.yaml` (see
`testcases\nextcloud_login.yaml` for a worked example).

---

## 2. Open the emulator

Create the AVD once (already done here as `qa_test`):

```powershell
avdmanager create avd -n qa_test -k "system-images;android-34;google_apis;x86_64" -d pixel_6
```

Boot it (visible window; drop `-no-window` off means a window shows):

```powershell
emulator -avd qa_test -no-audio -no-snapshot -gpu swiftshader_indirect
```

Wait until it is fully booted, then confirm it is `device` (not `offline`):

```powershell
adb wait-for-device
do { Start-Sleep 3; $b = adb -s emulator-5554 shell getprop sys.boot_completed } until ($b -match '1')
adb devices
```

Cold boot can take 2–5 minutes. Diagnose everything at once:

```powershell
py cli.py --check-env      # every row FOUND, "Live runner: READY"
```

**Expected output:**

```
Mobile QA Environment
────────────────────────────────────────────────
  python         ✓ FOUND    (required)  3.12.5
  adb            ✓ FOUND    (required for live run)  ...\platform-tools\adb.EXE
  aapt           ✓ FOUND    (required for live run)  ...\build-tools\34.0.0\aapt.EXE
  tesseract      ✓ FOUND    (required)  ...\Tesseract-OCR\tesseract.EXE
  emulator       ✓ FOUND    (optional)  ...\emulator\emulator.EXE
  uiautomator2   ✓ FOUND    (required for live run)
  pytesseract    ✓ FOUND    (required)
  Pillow         ✓ FOUND    (required)
  pyyaml         ✓ FOUND    (required)
  device         ✓ FOUND    (required for live run)  emulator-5554
────────────────────────────────────────────────
  Core tests:  READY
  Live runner: READY
```

If `device` is `MISSING`, the runner is `BLOCKED` — boot the emulator (§2). Every
other `MISSING` row names the tool to install.

---

## 3. How the flow runs (and run it)

`login.yaml` describes the flow; the runner executes it. First preview the plan
without a device:

```powershell
py cli.py --dry-run --test testcases\login.yaml
```

**Expected output** (the plan, then the env table; exits 0, no device touched):

```
Test case: Login with valid credentials
Package:   com.example.shop
Data:      email=test@example.com, password=Password123

Step plan (7 steps):
   0. launch
   1. type target={'id': 'com.example.shop:id/email'} value='{{email}}'
   2. type target={'id': 'com.example.shop:id/password'} value='{{password}}'
   3. tap  target={'text': 'Login'}
   4. assert text_exists value='Welcome'
   5. assert ocr_text_exists value='PAY NOW'
   6. assert screen_changed
```

Then the real end-to-end run — install → launch → type → tap → validate:

```powershell
py cli.py --apk sample-app\build\shop-login.apk --test testcases\login.yaml
```

**Expected output:**

```
Overall: PASS
Steps:  PASS=7
Report: reports\20260914-140831\report.html
```

The `run_id` (`20260914-140831`) is a timestamp, so it differs every run. Per
step the report shows **how** the target was found (`resolved_by`: `resource_id`
/ `text_exact`) and **how** the outcome was confirmed (`validated_by`:
`hierarchy` / `ocr` / `change`). The `PAY NOW` line is validated by real OCR of
the screenshot. Exit code is `0` on PASS, `1` on FAIL.

---

## 4. Negative path — proof it can't false-pass

```powershell
py cli.py --apk sample-app\build\shop-login.apk --test testcases\login_invalid.yaml
```

Wrong password → the app shows "Invalid credentials". The screen *changes*, but
`text_exists("Welcome")` must still **FAIL**. This is the guard that
change-detection never masks a failed assertion.

**Expected output** (exit code `1`):

```
Overall: FAIL
Steps:  PASS=4 · FAIL=1
Report: reports\20260914-141014\report.html
```

---

## 5. A real open-source app (Nextcloud)

```powershell
adb -s emulator-5554 shell pm clear com.nextcloud.client
py cli.py --apk apks\nextcloud.apk --test testcases\nextcloud_login.yaml
```

Drives Nextcloud's real login screen: open login → type a server address →
submit → the app reports "Could not find host" (validated by `hierarchy`) plus a
`screen_changed`. Real credential login needs a live server/account, so this
validates the reachable, offline-deterministic part of the flow.

**Expected output:**

```
Overall: PASS
Steps:  PASS=6
Report: reports\20260914-142249\report.html
```

---

## 6. Drive the device by hand (no runner, no YAML)

See each perceive/act/validate step in isolation:

```powershell
py examples\manual_flow.py --serial emulator-5554
```

Point it at any app with flags (defaults target the sample app):

```powershell
py examples\manual_flow.py --serial emulator-5554 `
  --package com.nextcloud.client --launch-activity com.nmc.android.ui.LauncherActivity `
  --pre-tap-text "Log in" `
  --email-id com.nextcloud.client:id/host_url_input --email "https://try.invalid" `
  --password-id "" --login-id com.nextcloud.client:id/text_input_end_icon `
  --expect-text "Could not find host" --expect-ocr ""
```

**Expected output** (defaults / sample app):

```
connected: emulator-5554

[0] launch com.example.shop
    activity: .MainActivity
[1] type email -> com.example.shop:id/email
[2] type password -> com.example.shop:id/password
[3] tap login

[4] validate
    text_exists 'Welcome'      -> PASS  validated_by=hierarchy
    ocr_text_exists 'PAY NOW'  -> PASS  validated_by=ocr

screenshots in ...\manual-demo
```

It prints each step and the validator verdict, saving `01_launched.png` …
`04_after_login.png` to `manual-demo\` (that folder is scratch / git-ignored).

---

## 7. Unit tests — the whole engine with no device

```powershell
py -m pytest -q      # expect all green
```

**Expected output:**

```
......................................................                   [100%]
54 passed in 5.63s
```

The engine is verified against a scripted `FakeDevice` + screenshots that real
Tesseract reads back — resolver, recovery, validator (including the
error-screen-does-not-pass guard), OCR, change detection, loader, report,
`settle`, and a full runner end-to-end.

---

## 8. Read the evidence

```powershell
$run = Get-ChildItem reports | Sort-Object Name -Descending | Select-Object -First 1
Start-Process "reports\$($run.Name)\report.html"
Get-Content "reports\$($run.Name)\timeline.json" | ConvertFrom-Json | Format-Table index,status,action,resolved_by,validated_by
```

**Expected `timeline.json` shape** (one row per step):

```
index status  action                  resolved_by  validated_by
----- ------  ------                  -----------  ------------
    0 PASS    launch
    1 PASS    type                    resource_id
    2 PASS    type                    resource_id
    3 PASS    tap                     text_exact
    4 PASS    assert:text_exists                   hierarchy
    5 PASS    assert:ocr_text_exists               ocr
    6 PASS    assert:screen_changed                change
```

---

## 9. How a run executes and where it is saved

**Where step execution starts.** `cli.py` → `cmd_run()` → `engine/runner.py`
`run()`. Inside `run()` the loop that actually walks the test case is:

```
engine/runner.py:64    for i, step in enumerate(tc["steps"]):
engine/runner.py:76        _run_assert(...)          # if the step is an assert
engine/runner.py:79        executor_mod.execute(...) # if the step is an action
engine/runner.py:91        ev.save_step(i, res)      # persist this step's evidence
```

Order inside `run()`:

1. `load_testcase()` parses + validates the YAML (bad file → clear error, no device touched).
2. `run_id = datetime.now().strftime("%Y%m%d-%H%M%S")` — the timestamp folder name.
3. `Evidence(run_id)` creates `reports/<run_id>/` (and `steps/`).
4. `device.install(apk)` if `--apk` was given.
5. **The step loop (line 64)** — each action goes to `executor.execute()`
   (observe → resolve+recover → perform → settle → observe → crash-gate); each
   assert goes to `_run_assert()` (the fixed-order validator). A `CRASH` or
   `BLOCKED` step aborts the rest, which are marked `SKIPPED`.
6. After the loop: `ev.write_logcat()`, `ev.write_timeline(meta)`, then
   `report.render(...)` writes `report.html`. `run()` returns
   `{overall, run_id, report_path, ...}`, which `cli.py` prints.

**Where output is saved** — one self-contained folder per run
(`engine/evidence.py`):

```
reports/<run_id>/
  steps/
    0/  before.png  after.png  hierarchy.xml  step.json      # per step:
    1/  before.png  after.png  hierarchy.xml  step.json      #   before/after
    2/  ...                                                    #   screenshots,
    …                                                         #   the after-hierarchy,
  logcat.txt          # full logcat captured since launch      #   and the full
  timeline.json       # every step (drives the HTML report)     #   ActionResult
  report.html         # the human report (open this)
```

- `before.png` / `after.png` — screenshots taken by `observe()` before and after the step.
- `hierarchy.xml` — the after-step accessibility tree.
- `step.json` — the full `ActionResult`: status, `resolved_by`, `validated_by`, recovery attempts, OCR matches, timings.
- `report.html` — sits in `reports/<run_id>/` and references the step PNGs by relative path, so keep the folder together when sharing.

There is **no committed demo folder** — each run generates its own
`reports/<run_id>/` (git-ignored). To share one, zip that whole folder.

---

## 10. Optional knobs (engine/config.py)

| Setting | Default | Effect |
|---------|---------|--------|
| `OCR_BACKEND` | `tesseract` | Set `easyocr` for stylised text (`pip install easyocr`, pulls torch). |
| `SETTLE_REQUIRE_SCREEN_STABLE` | `False` | Also wait for frames to be pixel-idle (animations), not just the hierarchy. |
| `OCR_MIN_CONFIDENCE` | `0.60` | OCR hit threshold. |
| `CHANGE_MIN` | `0.02` | `screen_changed` sensitivity. |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `adb`/`aapt` not found | New terminal; confirm `PATH` has the §0 dirs |
| `Live runner: BLOCKED` | Emulator not booted — see §2 |
| `device offline` | Wait for full boot; cold boot is 2–5 min |
| OCR asserts fail | `tesseract --version` must work and be on `PATH` |
| u2 connect hangs | `adb kill-server; adb start-server`, re-run |
| Selector not found on a real app | Re-dump the screen (§1B); ids differ by version |
