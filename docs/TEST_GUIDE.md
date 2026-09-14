# Test Guide — run and verify everything yourself

A top-to-bottom walkthrough: configure an APK → open the emulator → run the
login flow → validate → then every other flow (negative path, a real
open-source app, driving the device by hand) and how to read the evidence.
Commands are Windows PowerShell. Prebuilt example reports live in
[`docs/demo/`](demo/) — open any `report.html` in a browser.

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

---

## 3. How the flow runs (and run it)

`login.yaml` describes the flow; the runner executes it. First preview the plan
without a device:

```powershell
py cli.py --dry-run --test testcases\login.yaml
```

Then the real end-to-end run — install → launch → type → tap → validate:

```powershell
py cli.py --apk sample-app\build\shop-login.apk --test testcases\login.yaml
```

Expect `Overall: PASS`, `Steps: PASS=7`, and a report path. Per step the report
shows **how** the target was found (`resolved_by`: `resource_id` / `text_exact`)
and **how** the outcome was confirmed (`validated_by`: `hierarchy` / `ocr` /
`change`). The `PAY NOW` line is validated by real OCR of the screenshot.

---

## 4. Negative path — proof it can't false-pass

```powershell
py cli.py --apk sample-app\build\shop-login.apk --test testcases\login_invalid.yaml
```

Wrong password → the app shows "Invalid credentials". The screen *changes*, but
`text_exists("Welcome")` must still **FAIL**. Expect `Overall: FAIL`
(`PASS=4 · FAIL=1`). This is the guard that change-detection never masks a
failed assertion.

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

It prints each step and the validator verdict, saving screenshots to
`manual-demo\`.

---

## 7. Unit tests — the whole engine with no device

```powershell
py -m pytest -q      # expect all green
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

Prebuilt examples are committed in [`docs/demo/`](demo/):
`sample-login-pass/`, `sample-login-fail/`, `nextcloud-login/` — open each
`report.html`.

---

## 9. Optional knobs (engine/config.py)

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
