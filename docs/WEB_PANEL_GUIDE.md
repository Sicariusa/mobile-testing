# Web Panel Guide — run the whole test loop from the browser

The **Mobile QA Control Panel** is a local web page over the test engine. After
you start it once, everything else — boot the emulator, install an app, launch
it, capture screens, preflight a test, run it, read the diagnostics and the
report — happens in the browser. No new dependencies: it is Python's standard
`http.server` plus one static HTML file (`webapp/`).

The only step that stays manual is **driving the app between captures** — a human
decides which screens matter.

---

## 1. Start the panel

**Easiest — double-click** `start-web.bat` (repo root). It starts the server and
opens `http://localhost:8765` in your browser.

**Or from a terminal:**

```powershell
cd C:\Users\abdo2\Documents\GitHub\mobile-testing
py cli.py web              # → http://localhost:8765   (Ctrl+C to stop)
py cli.py web --port 9000  # a different port
```

The server and the page are one process — closing the terminal (or Ctrl+C) stops
it. Read-only panels work with no device connected; anything that touches the
phone (start-emulator, launch, capture, run) needs one.

---

## 2. The panel at a glance

```
┌ Mobile QA · Control Panel ──────────[live ready] [device emulator-5554] [Refresh]┐
│                                                                                   │
│  ENVIRONMENT                         SCREENS (PRE-FETCH LIBRARY)                   │
│  [ qa_test ▾] [Start emulator][Stop] [ package……… ] [Load] [Launch app]           │
│  python   ✓ FOUND                    [ label……… ]   [Capture current screen]      │
│  adb      ✓ FOUND …                  (library table appears here)                 │
│                                                                                   │
│  TEST CASES                                                                       │
│  Install before run (optional): [ — no APK — ▾]                                   │
│  Name                Package                 Steps   [Preflight][Run]             │
│                                                                                   │
│  REPORTS        (PASS/FAIL tags · run id · View → opens report.html inline)       │
│                                                                                   │
│  [ log — every action prints here, newest on top ]                                │
└───────────────────────────────────────────────────────────────────────────────────┘
```

The two **pills** in the header are your status: the first is environment
(`live ready` / `core ready` / `not ready`), the second is the device
(`device emulator-5554` in green, or `no device` in red). The **log strip** at
the bottom records every action with a PASS/FAIL colour, newest first.

---

## 3. Full loop from zero (the happy path)

Starting with nothing running:

1. **Start the emulator.** In *Environment*, pick your AVD (`qa_test`) and click
   **Start emulator**. A window opens; the panel polls every 5 s and the device
   pill turns green when it finishes booting (~30–60 s). No terminal.
2. **(Optional) install the app.** In *Test cases*, open **Install before run**
   and choose an APK (e.g. `apks/sauce.apk`). Leave it on *"— no APK, use
   installed —"* if the app is already on the device.
3. **Launch the app.** In *Screens*, type the package
   (`com.swaglabsmobileapp`) and click **Launch app** — it opens to its home
   screen. Drive it by hand (in the emulator window) to the first screen you
   want to test.
4. **Capture screens into the library.** Type a name (`login`) in the label box
   and click **Capture current screen**. Drive to the next screen (`catalog`,
   `product`), capture each. The library table updates with element counts.
5. **Preflight a test.** In *Test cases*, click **Preflight** next to your test.
   The log lists each target as `✓ found on '<screen>'` or `✗ not captured`, and
   ends with **"All targets known."** when every target maps to a captured
   screen — so you know it will resolve before spending a live run.
6. **Run it.** Click **Run**. The panel drives the device and logs
   `→ PASS (PASS=14)`. On a non-PASS, per-step **diagnostics** print right below
   (reason, the screen it was on, and the nearest ranked on-screen matches).
7. **Read the report.** In *Reports*, click **View** on the newest run to open
   its `report.html` inline.
8. **Stop the emulator** when done — *Environment* → **Stop**.

That is the entire workflow with no terminal beyond step 1's `py cli.py web`
(or the `.bat`).

---

## 4. Every feature, panel by panel

### Environment
- **Tool + device readiness** — the same checks as `py cli.py doctor`, live.
- **AVD picker** — populated from `emulator -list-avds`.
- **Start emulator** — boots the chosen AVD in a window (detached; the panel
  keeps working while it boots) and auto-refreshes until the device appears.
- **Stop** — kills the running emulator (`adb emu kill`).

### Screens (pre-fetch library)
- **package box + Load** — show the captured screen library for a package
  (label, activity, element / tappable / field counts).
- **Launch app** — open that package to its launcher screen so you can drive it.
- **label box + Capture current screen** — snapshot whatever is on the device
  now into the library under that name.

> **The label is cosmetic.** Screens are matched at run time by
> `structural_fingerprint` (the app's real activity + element structure), never
> by the name you type — call a screen `products` while the developer's activity
> is `CatalogActivity`, no effect. Only the visible **text / id** in a test's
> `target:` has to mirror the app.

### Test cases
- **Install before run (optional)** — pick an APK from `apks/` to install
  immediately before the run (or none, to use what's installed).
- **Preflight** — match a test's targets against the library with **no device**;
  tells you which are known and which will be resolved live.
- **Run** — execute the test on the device; result + diagnostics go to the log,
  the report appears in *Reports*.

### Reports
- List of past runs with a **PASS / FAIL / other** tag and run id.
- **View** opens that run's `report.html` inline in the page.

### Log strip
Every action's outcome, newest on top, colour-coded. Run diagnostics and
preflight results render here.

---

## 5. Endpoint reference

Thin JSON over the same functions the CLI uses (`webapp/server.py`).

| Method + path | Does | Device? |
| --- | --- | --- |
| `GET /api/env` | tool/device readiness | no |
| `GET /api/testcases` | list `testcases/*.yaml` | no |
| `GET /api/screens?package=…` | the screen library for a package | no |
| `GET /api/reports` | past runs (newest first) | no |
| `GET /api/avds` | installed AVDs | no |
| `GET /api/apks` | APKs under `apks/` | no |
| `GET /api/preflight?test=…` | match a test's targets to the library | no |
| `POST /api/emulator` | `{action:"start"\|"stop", avd?}` | — |
| `POST /api/launch` | `{package}` → open the app | yes |
| `POST /api/inspect` | `{label}` → capture current screen | yes |
| `POST /api/run` | `{test, apk?}` → run; returns counts + diagnostics | yes |
| `GET /reports/<run>/…` | serve a report file (path-escape guarded) | no |

You can hit these directly too, e.g.:

```powershell
curl http://localhost:8765/api/avds
curl "http://localhost:8765/api/preflight?test=testcases/sauce_add_to_cart.yaml"
```

---

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Device pill stays red after **Start emulator** | Boot takes ~30–60 s; the panel polls for ~90 s. If it never turns green, check the emulator window opened, and that `qa_test` boots from a terminal. |
| **Launch app** says "could not launch" | The package isn't installed, or the name is wrong. Install it via the APK picker, or check `adb shell pm list packages`. |
| **Capture** fails | No device, or the app isn't in the foreground. Launch/drive to the screen first. |
| **Preflight** says "No screens captured" | Capture the app's screens first (Screens panel). |
| Run is slow | Host load (e.g. a game) can ANR the emulator; the engine also runs OCR as a last-resort fallback. Neither is an engine bug. |
| Panel won't load | The server isn't running — start it (`py cli.py web` / `start-web.bat`) and confirm the port. |

---

## 7. What still needs a terminal

Only **starting the server** (`py cli.py web`, or double-click `start-web.bat`).
Everything else — emulator, install, launch, capture, preflight, run, reports —
is in the panel. See also [`TEST_GUIDE.md`](TEST_GUIDE.md) for the engine
internals and the CLI equivalents of each button.
