# Architecture

A walkthrough of how the runner is put together, so a newcomer can find their
way around and extend it safely.

## The layers

```
        Android app
             │
   ┌─────────▼─────────┐  device.py
   │   DEVICE LAYER    │  the ONLY code that touches ADB / uiautomator2.
   │                   │  Abstract Device + Element interface; AndroidDevice
   └─────────┬─────────┘  is the real impl, FakeDevice (tests) is a stand-in.
             │
   ┌─────────▼─────────┐  observation.py, ocr.py, resolver.py,
   │  PERCEPTION LAYER │  stabilize.py, recovery.py
   │                   │  turn raw device state into Observations, locate
   └─────────┬─────────┘  targets (selectors → OCR), and recover.
             │
   ┌─────────▼─────────┐  validator.py, executor.py, runner.py
   │  EXECUTION LAYER  │  perform a step, validate an outcome, drive the loop.
   └─────────┬─────────┘
             │
   ┌─────────▼─────────┐  evidence.py, report.py
   │  EVIDENCE LAYER   │  persist artifacts + timeline.json, render report.html
   └───────────────────┘
```

The golden rule: **everything above the device layer reaches the device only
through the `Device` interface.** That single abstraction is what lets the
entire engine run against a `FakeDevice` with no Android present — swap
`AndroidDevice` for `FakeDevice` and nothing else changes.

### Debug map

| Symptom | Layer to look at |
|---|---|
| can't connect / install | `device.py` |
| can't see the UI | `observation.py` |
| can't find a button | `resolver.py` / `ocr.py` |
| target never reached | `recovery.py` |
| action didn't happen | `executor.py` |
| wrong PASS/FAIL | `validator.py` |
| report looks wrong | `evidence.py` / `report.py` |

---

## The four shared data models (`engine/models.py`)

Every module speaks these instead of ad-hoc dicts/tuples. They all serialise to
JSON via `as_dict()`.

- **`Observation`** — a concrete point in time: `timestamp`, `package`,
  `activity`, `screenshot_path`, `hierarchy_xml`, `keyboard_visible`. The pure
  `Observation.transition(before, after)` derives `activity_changed`,
  `hierarchy_changed`, `new_text`/`removed_text` — the substrate for change
  detection and future autonomous reasoning.
- **`ResolutionResult`** — how a target was located: `element` **or**
  `coordinates`, the `strategy` (`resource_id` | `text_exact` | `text_contains`
  | `desc` | `ocr`), a `confidence` (1.0 for selector hits, OCR score for OCR),
  and the ordered `attempts`.
- **`RecoveryTrace`** — the ordered story of reaching a stubborn target.
- **`ActionResult`** — the full outcome of one step. `resolved_by` /
  `validated_by` (each with a confidence) are **first-class** here, plus
  `recovery`, `before`/`after` observations, and a `crash_signature`.

### How they flow

```
runner ──▶ executor.execute(step)
              observe() ─────────────▶ Observation (before)
              recovery.reach(target) ─▶ (ResolutionResult, RecoveryTrace)
              perform(...)
              observe() ─────────────▶ Observation (after)
           ◀── ActionResult(status, resolved_by, validated_by, recovery, …)
runner ──▶ validator.validate(assert, before, after) ─▶ ValidationOutcome
runner ──▶ evidence.save_step(ActionResult) ─▶ steps/<n>/…, timeline.json
runner ──▶ report.render(timeline) ─▶ report.html
```

---

## The executor loop (`engine/executor.py`)

For an **action** step:

```
before = observe(device)
if targeted action (tap/type/long_click):
    resolution, recovery = recovery.reach(target)   # selectors → retry → keyboard → scroll → OCR
    if not resolution.found:  return BLOCKED (with the RecoveryTrace)
    perform(action, resolution, value)              # element.click / set_text, or tap_xy + input_text
settle(device)                                      # wait for the screen to stabilise
after = observe(device)
status = CRASH if fatal-in-logcat else PASS
```

**Assertions** are handled by the runner (not the executor) because a
`screen_changed` assertion must reason over the **preceding action's**
before/after — an assert step performs no action of its own.

---

## The validation algorithm (`engine/validator.py`)

Deterministic and fixed-order:

1. **Crash gate first** — any `FATAL_LOGCAT_MARKERS` line ⇒ `CRASH` +
   `crash_signature`.
2. **Per assertion type** (never a generic fallback chain):

   | type | how it passes |
   |---|---|
   | `text_exists` | hierarchy match → else OCR ≥ `OCR_MIN_CONFIDENCE` → else FAIL |
   | `ocr_text_exists` | OCR only |
   | `element_exists` | id/text/desc present in the hierarchy |
   | `activity_is` | current activity matches |
   | `screen_changed` | `change_ratio(before, after) ≥ CHANGE_MIN` |

3. `change_ratio` = **max** of a normalised hierarchy diff and a screenshot
   pixel-diff ratio.

> **Design guard:** `screen_changed` is the *only* assertion validated by change
> detection, and it is **evidence of a state transition, not semantic proof** of
> any other expectation. A tap that lands on an error screen changes the screen
> but is not a success — so `text_exists("Welcome")` must fail there, and does.
> (`tests/test_validator.py::test_error_screen_does_not_pass_success_assertion`.)

---

## Configuration (`engine/config.py`)

All tunables in one place: `OCR_MIN_CONFIDENCE`, `CHANGE_MIN`, settle timings,
recovery/scroll bounds, thumbnail width, fatal-logcat markers. No other module
hard-codes a threshold.

---

## Where to start reading

1. `engine/models.py` — the vocabulary.
2. `engine/runner.py` — the top-level loop; follow one step through it.
3. `engine/executor.py` + `engine/validator.py` — the core decisions.
4. `tests/test_runner.py` + `tests/fake_device.py` — see it all exercised end to
   end without a device.

---

## Extending it

**Add a new action** (e.g. `pinch`):
1. Add the verb to `KNOWN_ACTIONS` (and `TARGETED_ACTIONS` if it needs a target)
   in `engine/loader.py`.
2. Handle it in `executor.execute` / `_perform`.
3. Add the primitive to the `Device` interface and both implementations
   (`AndroidDevice`, `FakeDevice`).

**Add a new assertion type** (e.g. `toast_shown`):
1. Add it to `ASSERT_TYPES` in `engine/loader.py`.
2. Add a branch in `validator.validate` returning a `ValidationOutcome` with the
   right `validated_by`.
3. Cover it in `tests/test_validator.py`.

**Swap in a live device:** construct `AndroidDevice` via `device.connect()`
instead of `FakeDevice`. The engine above the device layer is unchanged — this
is the seam the whole design is built around, and the same seam a future
autonomous planner would sit above, consuming `Observation` + `ActionResult` +
`RecoveryTrace` and deciding the next step.
