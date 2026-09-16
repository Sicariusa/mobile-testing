# Audit, Fixes, and Live-Safe Reverts

This document records a full arc of work on the `enhance` branch: an adversarial
audit of the engine, the fixes applied for it, a live-run regression those fixes
introduced, the reverts that restored working behaviour, and the live
verification that closed it out.

**TL;DR** — The audit findings were sound. A few *fixes* changed real-device
behaviour and were validated only by the FakeDevice test suite, which cannot see
device behaviour, so live runs broke. The behaviour-changing fixes were reverted
to match `main`; only result-neutral improvements ship, plus the two
false-verdict fixes as **opt-in**. Verified live: add-to-cart passes 14/14 on
both branches.

---

## 1. The audit

A multi-agent adversarial audit of the whole repository (~6,900 LOC): six
dimension auditors read the source and fanned out; every substantive finding was
handed to an independent skeptic instructed to refute it and reproduce the
failure in code. Only survivors were kept.

- **29 findings** verified — 2 high, 17 medium, 10 low; **0 refuted**. Health
  score 54/100.
- Themes: loose text/identity matching, execution/recovery correctness, an
  unauthenticated local web panel, evidence durability, redundant device
  round-trips, and tests that gave false confidence.
- Full report: [`AUDIT-2026-09-16.md`](AUDIT-2026-09-16.md) and the interactive
  [`perception-engine-audit.html`](perception-engine-audit.html).

The three **web-panel security findings** (CSRF/Origin, package command
injection, path traversal) were deliberately **parked**, not implemented.

## 2. The fixes — and the regression

26 findings were implemented, each with tests; the suite went from 121 to 154
passing. **All green.** The branch was then run against a real emulator and
**the tool stopped working** on the live path.

### Root cause

Every automated test runs against a `FakeDevice`. That is the project's great
strength for logic testing — but it means **any change whose effect only appears
on a real device passes the suite regardless of whether it works.** Several fixes
changed the device-interaction layer, so broken behaviour shipped behind 154
green tests.

### What actually broke

| # | Change (audit finding) | Why it broke live |
|---|---|---|
| 1 | **Keyboard dismiss**: BACK → ESCAPE (`keyevent 111`) (C4, *low*) | Real Android IMEs ignore ESCAPE, so the soft keyboard stayed up and covered the next field/button. Every **type → tap** flow (login, all sauce flows) stalled at the first typed step. This was the "nothing works" bug. |
| 2 | **`settle()`** stricter (D3) | Added a wait for the action's effect (up to ~timeout/2 ≈ 2.5s per step) plus a two-stable-pair requirement, so runs on any tap that didn't restructure the tree looked hung. |

Secondary behaviour changes with real (if smaller) drift risk: whole-word text /
OCR matching by default, `not_visible` FAILing when OCR can't run, incremental
crash-gate logcat, saves that raise on IO error, and a bounded hierarchy-diff.

## 3. The reverts — what was kept vs restored

The behaviour-changing implementations were reverted to `main`'s behaviour. The
result-neutral improvements were kept.

### Reverted to `main` behaviour

- Keyboard dismissal back to **BACK**.
- `settle()` back to returning on the first stable pair (kept only the safe guard
  that a failed dump is never "settled").
- Text / OCR matching back to **substring** by default (strict is now opt-in —
  see §5).
- `not_visible` no longer FAILs when OCR is unavailable.
- Per-step crash gate back to a **full** logcat scan.
- Library / selector-cache saves are atomic but **swallow** IO errors (can't abort
  a run).
- Hierarchy diff back to the full `SequenceMatcher` ratio.

### Kept (cannot change a live verdict or interaction)

- Report no longer inlines full hierarchy XML; tolerant status counts; no
  fabricated "before" thumbnail for point-in-time assertions.
- Collision-proof `run_id` (random suffix).
- Atomic file writes (temp + `os.replace`); `.`/`..` package sanitiser.
- Loader rejects an `element_exists` that carries only `value`.
- Resolver ranks the full candidate set (role-fit target not truncated out).
- Real `long_click` (u2 long press, coordinate fallback).
- Per-screenshot OCR memoisation; OCR evidence only collected when relevant.
- `activity_is` component-boundary match; numeric assertion value coerced to str;
  a step error no longer discards the run's report.
- Crawler no longer abandons a screen when Back returns it scrolled.

## 4. Live verification

Run against a real `qa_test` emulator (windowed), on **both branches**:

- **`testcases/sauce_add_to_cart.yaml`** — install APK → login (type user/pass →
  **submit**, the keyboard step) → open product → add to cart → button flips to
  REMOVE, cart shows 1 → Back → state persists. **Overall PASS, 14/14 steps on
  both `enhance` and `main`**, step-for-step identical.
- **Web panel** — every feature driven both over HTTP and through the browser UI:
  environment probe, list test cases / reports / screens / AVDs / APKs, launch
  app, capture screen, rename / checkpoint / remove, preflight, run, static report
  serving, and the `../` path-escape guard. **Identical on both branches.**
- **Auto-crawl** excluded from this verification (pre-existing behaviour, unrelated
  to this work).

### Known pre-existing issue (both branches)

Launching the panel as `py -m webapp.server` crashes on a Windows cp1252 console
because of a literal `→` in the startup `print` (`UnicodeEncodeError`). It only
works because `py cli.py web` reconfigures stdout to UTF-8. Not introduced here;
`webapp/server.py` is unchanged between branches.

## 5. Using the opt-in strict matching

The two false-verdict fixes from the audit are preserved as an **opt-in** so they
never change existing behaviour by default. In a test case:

```yaml
- assert:
    type: text_exists
    value: "Success"
    match: word     # whole-word / contiguous-token; 'Success' won't match 'Unsuccessful'
# match: exact      # full normalised equality
# (default is substring 'contains' — unchanged from main)
```

## 6. Lesson

A change to the device-interaction layer (keyboard, gestures, settle timing,
crash detection) is **not verified by the FakeDevice suite** — it must be run on a
real device or emulator before it is trusted. The suite proves logic; only a live
run proves interaction.
