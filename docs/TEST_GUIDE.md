# Test Guide — run and verify everything yourself

A top-to-bottom walkthrough: configure an APK → open the emulator → run the
login flow → validate → then every other flow (negative path, a real
open-source app, driving the device by hand) and how to read the evidence.
Commands are Windows PowerShell. Every run writes its own timestamped report to
`reports/<run_id>/report.html` — see [§9](#9-how-a-run-executes-and-where-it-is-saved).

---

## The 30-second mental model

You write **intent** (visible labels). The engine perceives the live screen,
finds the real element, binds it, and remembers it.

```
APK + testcase.yaml  (targets are labels: "Email", "Password", submit)
      │
      ▼
 cli.py ──▶ probe env ──▶ connect device ──▶ install APK ──▶ for each step:
                                     PERCEIVE  observe(before) → ScreenObservation
                                     RESOLVE   id → cache(learned) → rank(label) → OCR
                                     RECOVER   scroll / hide-keyboard / dismiss-dialog
                                     ACT       tap / type / submit
                                     OBSERVE   settle → observe(after)
                                     VALIDATE  text_exists / not_visible / *_changed
                                     RECORD    png + xml + json  (+ learned id → bindings.json)
      │
      ▼
 reports/<run_id>/report.html   (per step: resolved_by, validated_by, failure_reason)
 .selector-cache/<package>.json (label → real id, reused next run; self-heals)
```

No manual id editing: a target of `"Login"` is ranked against the live screen
and bound to `…:id/login` automatically. Nothing in the engine talks to Android
except `engine/device.py`, so the whole thing is unit-tested against a fake
device with no hardware.

---

## The new flow in practice — bring any app, write no ids

This is the whole point of the rework: you do **not** hand-write selectors. The
loop to bring up a brand-new app (say `com.example.app`) is three steps.

**Step 1 — install and inspect the screen (debug mode, no test file).** This is
how you *see* what the engine sees and get the real ids for free:

```powershell
adb install apps.apk                       # or install-multiple for a split bundle
adb shell monkey -p com.example.app -c android.intent.category.LAUNCHER 1
py cli.py inspect --label home             # scan the CURRENT screen
```

`inspect` writes `screens\home\` = `screenshot.png`, `hierarchy.xml`,
`observation.json`, and `inventory.md` (a table of every element: kind, real
`resource_id`, text, flags, bounds) plus the screen's **structural
fingerprint**. Run it again after each navigation (`--label login`,
`--label cart`) to map a multi-screen story. No YAML, no editing — just look.

**Step 2 — write the test as intent.** Use the *visible labels* you saw; the
engine binds them to the ids from step 1 at run time:

```yaml
name: "Login"
package: com.example.app
data: { email: test@example.com, password: Password123 }
steps:
  - action: launch
  - action: enter_text
    target: "Email"          # label, not id
    value: "{{email}}"
  - action: enter_text
    target: "Password"
    value: "{{password}}"
  - action: submit           # finds the login/submit button itself
  - assert: { type: activity_changed }
  - assert: { type: text_exists, value: "Welcome" }
```

**Step 3 — run it.** The engine perceives, resolves each label, taps/types,
validates, and records everything:

```powershell
py cli.py --apk apps.apk --test testcases\login.yaml
```

Open `reports\<run_id>\report.html` for the per-step evidence, and
`reports\<run_id>\bindings.json` for the **label → real id** map it learned
(also cached to `.selector-cache\com.example.app.json` and reused next run). If a
step can't find its target, the report gives a `failure_reason` plus ranked
**suggestions** of the real on-screen selectors — paste the right label back and
re-run. Full reference in [§9b](#9b-semantic-targets-auto-binding-inspect--replay).

> **Popups & permissions** (e.g. a notification prompt, "While using the app")
> are auto-dismissed by the recovery layer before the target is sought, so a
> first-run dialog doesn't break the flow. `inspect` shows the dialog too, with a
> `dialog` window flag.

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

It prints one row per tool (python, adb, aapt, tesseract, emulator,
uiautomator2, pytesseract, Pillow, pyyaml, device) plus `Core tests` and
`Live runner` readiness. If `device` is `MISSING`, the runner is `BLOCKED` —
boot the emulator (§2). Every other `MISSING` row names the tool to install.

---

## 3. How the flow runs (and run it)

`login.yaml` describes the flow; the runner executes it. First preview the plan
without a device:

```powershell
py cli.py --dry-run --test testcases\login.yaml
```

It prints the parsed test case (name, package, data) and the numbered step plan,
exits `0`, and never touches a device — use it to sanity-check a YAML before a
live run.

Then the real end-to-end run — install → launch → type → tap → validate:

```powershell
py cli.py --apk sample-app\build\shop-login.apk --test testcases\login.yaml
```

It prints `Overall: PASS`, a per-status step count, and the path to a fresh
`reports\<run_id>\report.html`. The `run_id` is a timestamp, so it differs every
run. Per step the report shows **how** the target was found (`resolved_by`:
`resource_id` / `text_exact` / `ranked` / `cache` / `ocr`) and **how** the
outcome was confirmed (`validated_by`: `hierarchy` / `ocr` / `change`). Exit code
is `0` on PASS, `1` on FAIL.

---

## 4. Negative path — proof it can't false-pass

```powershell
py cli.py --apk sample-app\build\shop-login.apk --test testcases\login_invalid.yaml
```

Wrong password → the app shows "Invalid credentials". The screen *changes*, but
`text_exists("Welcome")` must still **FAIL**. This is the guard that
change-detection never masks a failed assertion.

It prints `Overall: FAIL` (exit code `1`) with the failing step counted — the
`text_exists("Welcome")` assert fails even though the screen changed.

---

## 5. A real open-source app (Nextcloud)

```powershell
adb -s emulator-5554 shell pm clear com.nextcloud.client
py cli.py --apk apks\nextcloud.apk --test testcases\nextcloud_login.yaml
```

Drives Nextcloud's real login screen: open login → type a server address →
submit → the app reports "Could not find host" (validated by `hierarchy`) plus a
`screen_changed`. Real credential login needs a live server/account, so this
validates the reachable, offline-deterministic part of the flow. It prints
`Overall: PASS` with the report path.

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

It prints each perceive/act/validate step and the validator verdict
(`validated_by=hierarchy` / `ocr`), saving `01_launched.png` …
`04_after_login.png` to `manual-demo\` (that folder is scratch / git-ignored).

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

`timeline.json` has one row per step — `index`, `status`, `action`,
`resolved_by` (how the target was found) and `validated_by` (how the outcome was
confirmed) — which is what the table above renders.

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

## 9b. Semantic targets, auto-binding, inspect & replay

You don't have to hard-code `resource-id`s. A target can be a **label** and the
engine resolves it on the live screen, then caches the real id per screen
(`reports/<run_id>/bindings.json` + `.selector-cache/<package>.json`, reused on
later runs; a stale binding self-heals).

```yaml
- action: enter_text
  target: "Email"          # a string label — no id needed
  value: "{{email}}"
- action: submit           # finds the submit/login button itself
- assert: { type: activity_changed }
- assert: { type: not_visible, value: "Loading" }
```

Actions: `tap · type · enter_text · submit · long_click · swipe · back · wait`.
Asserts add `not_visible` and `activity_changed`. A tap/submit auto-dismisses the
keyboard first. A failed step reports a precise `failure_reason`
(`TARGET_NOT_FOUND`, `UNEXPECTED_SCREEN`, …) plus ranked **suggestions** of the
real on-screen selectors.

Fetch any screen's selectors, or re-print a finished run, with no re-execution:

```powershell
py cli.py inspect --label login     # → screens/login/{observation.json,hierarchy.xml,screenshot.png,inventory.md}
py cli.py replay                    # re-print the latest run's verdicts
py cli.py doctor                    # environment check
```

---

## 9c. The six phases — what each added and how to exercise it

The perception-first rework landed in six phases. Each is independently
testable; the unit suite (`py -m pytest -q`) covers all of them.

| # | Phase | What it added | Exercise it |
|---|-------|---------------|-------------|
| 1 | **Perception** | one `ScreenObservation` per screen (elements, structural/content fingerprints, window flags) + `inspect` debug mode | `py cli.py inspect --label home` → read `screens\home\inventory.md`; `py -m pytest -q tests\test_inspect.py` |
| 2 | **Resolution + auto-bind** | candidate ranking (label→id), self-healing per-screen cache | run any semantic test → check `reports\<run>\bindings.json` and `.selector-cache\<pkg>.json`; `tests\test_locator.py` |
| 3 | **Semantic actions** | string/label targets, `enter_text`, `submit`, keyboard auto-dismiss | `py cli.py --test testcases\shop_login_semantic.yaml` (zero ids); `tests\test_semantic.py` |
| 4 | **Validation** | `not_visible`, `activity_changed` over before/after | `tests\test_validation_extra.py` |
| 5 | **Recovery** | detect a blocking dialog/permission → dismiss → re-resolve | `tests\test_recovery_dialog.py`; live: launch an app with a first-run permission prompt |
| 6 | **CLI** | `inspect` · `replay` · `doctor` subcommands, richer failure output | `py cli.py inspect`, `py cli.py replay`, `py cli.py doctor`; `tests\test_cli_replay.py` |

Full engine-evolution write-up (old vs new, every fix + the file/line it lives
in) is in **[index.html](index.html)** → *Old engine → new engine*, *The six
phases*, and *Fixes & code map*. A dated summary of every change is in
[CHANGELOG.md](../CHANGELOG.md).

**Minimal end-to-end proof (no ids, live):**

```powershell
py cli.py --apk apks\<app>.apk --test testcases\shop_login_semantic.yaml
```

Watch it fetch the real ids, bind the labels, and pass — then open
`reports\<run_id>\bindings.json` to see the learned `label → resource-id` map.

---

## 9d. Speed, the screen library, preflight & the web panel

**Faster runs (hierarchy memo).** Every step used to issue many
`dump_hierarchy()` calls (each a slow adb uiautomator dump). The live device now
memoizes the hierarchy within one screen state and invalidates it after any
action (`config.HIERARCHY_CACHE`, default on); `settle` and recovery force-fresh
reads so change detection is unaffected. Measured on `sauce_vague.yaml`:
**23 → 6 device dumps (74% fewer), 51 s → 29 s.** Toggle off to compare:

```powershell
py -c "import engine.config as c; c.HIERARCHY_CACHE=False"   # (or edit config.py)
```

**Pre-fetch a screen library.** Capture the screens you'll test by driving the
app, so the engine has a map before a run (and can scroll *toward* an off-screen
target instead of guessing):

```powershell
adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1
py cli.py inspect --label catalog --into-library     # drive to each screen, capture
py cli.py screens --package <package>                # list the library
```

Bundles land in `screens\<package>\` and the library index in
`screens\<package>\library.json` (keyed by each screen's structural fingerprint).

> **The label you pick is cosmetic.** Matching is by `structural_fingerprint`
> = `sha1(activity + sorted id:class:desc)` — the app's real runtime activity and
> element structure, captured live — never by the name you type. Call a screen
> `products` while the developer's activity is `CatalogActivity`: zero effect.
> Likewise test `target:`s match on-screen **text / desc / id**, not screen names.
> (Proof: SwagLabs' `login` / `catalog` / `product` all report
> `activity=.MainActivity` yet match correctly via distinct fingerprints.) The
> only thing that must mirror the app is the **visible text/id** in your steps.

**Preflight — match a test to the library (no device).** Before a live run, see
which targets are already known and which will be resolved live:

```powershell
py cli.py --preflight --test testcases\sauce_add_to_cart.yaml
```

Each targeted step prints `✓ found on '<screen>'` or `✗ not in any captured
screen`; exit `0` when all are known.

**Run diagnostics.** A non-PASS run now prints, per blocked/failed step, the
`failure_reason`, the screen it was on, and the nearest ranked on-screen matches
— the same data that is in `timeline.json`, surfaced in the terminal.

**Web control panel — do everything from the browser.** A local page over the
engine. Start it once:

```powershell
py cli.py web                 # → http://localhost:8765  (Ctrl+C to stop)
```

…or just **double-click `start-web.bat`** — it starts the server and opens the
page. From the panel, with no further terminal:

| Panel | You can |
| --- | --- |
| Environment | see tool/device readiness; **pick an AVD → Start / Stop the emulator** (device pill turns green when it boots) |
| Screens | type a package → **Launch app** to its home screen, drive it, name the screen → **Capture** into the library; **Load** to list |
| Test cases | optionally **pick an APK to install before a run**; **Preflight** a test (targets vs library, no device); **Run** it |
| Reports | open any run's `report.html` inline; a non-PASS **Run prints per-step diagnostics right in the panel** |

The only manual step left is *driving the app between captures* — a human decides
which screens matter. Read-only panels (env, list, preflight, reports) work with
no device; start-emulator, launch, capture and run need one. It is a stdlib
server (`webapp/server.py`) + one static page (`webapp/index.html`) — no new
dependencies. Endpoints: `GET /api/{env,testcases,screens,reports,avds,apks,
preflight}`, `POST /api/{inspect,run,emulator,launch}`; report serving is
path-escape guarded.

> **Full step-by-step walkthrough:** [`WEB_PANEL_GUIDE.md`](WEB_PANEL_GUIDE.md) —
> starting the panel, every feature, the whole loop from zero, an endpoint
> reference, and troubleshooting.

**Validated live (SwagLabs on the `qa_test` emulator).** `sauce.yaml`,
`sauce_negative.yaml`, `sauce_vague.yaml` → **PASS 6/6** each;
`sauce_add_to_cart.yaml` → **PASS 14/14** — the flow that was `BLOCKED` before
this round (non-clickable product title + off-screen add-to-cart), now resolved
by clickable-ancestor promotion and directed scroll. `login` / `catalog` /
`product` captured into the library; `--preflight` matched **all 4** targets with
no device ("All targets known."); the web panel served env, library, tests, and
reports (path-traversal → 404). 86 unit tests green.

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
