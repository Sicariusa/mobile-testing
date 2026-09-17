# Showcase videos

Two cuts of the Mobile QA Test Runner reel. Both are benefit-led product films —
they show what the runner *does* (drives your app, maps and captures screens,
recovers when blocked, and produces a clear pass/fail report) without exposing
how the engine works.

| | format | length | file |
|---|---|---|---|
| **Wide** (landscape / embeds) | 1920×1080 · 16:9 | ~38s | `mobile-qa-showcase.mp4` |
| **Vertical** (TikTok / Reels / Shorts) | 1080×1920 · 9:16 | ~43s | `mobile-qa-showcase-vertical.mp4` |

![poster](mobile-qa-showcase-poster.png)

Both are H.264 (yuv420p, faststart) and play everywhere. Posters:
`mobile-qa-showcase-poster.png`, `mobile-qa-showcase-vertical-poster.png`.

## Wide cut — short & QA-focused

A tight ~38s cut built around the QA story: automated test cases and a pass/fail
report.

1. **Hook** — *"Test cases that run themselves."*
2. **Automated run** — 5 test cases execute on their own (no taps), stamping
   **PASS / PASS / PASS / FAIL / PASS** while the app is driven in a phone beside
   the runner.
3. **Report** — **4 Passed / 1 Failed**, an 80% pass-rate ring, and the failed
   case expanded to a defect detail
   (*Expected "Order placed" ✓ / Got "Payment declined" ✕*).
4. Close — Automated · Resilient · Pass / fail proof.

The runner and the report use the same five cases, so the numbers line up.

## Vertical cut

The same story, condensed for social: title → drives your app → finds every
control → recovers when blocked → captures every step → Welcome / `PASS` → close.

## Rebuild either one

Rendered from a self-contained animated page and screen-recorded, so each
regenerates identically. The recorder is configurable via env vars:

```bash
# Wide (16:9) — the default
SHOW_MS=56000 node tools/record_showcase.mjs            # → media/*.webm

# Vertical (9:16)
SHOW_PAGE=docs/showcase/showcase-vertical.html VID_W=1080 VID_H=1920 SHOW_MS=42000 \
  node tools/record_showcase.mjs

# transcode to a shareable MP4 with any full ffmpeg build (trim the black head)
ffmpeg -ss 0.4 -i media/<recording>.webm \
  -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 19 -preset slow \
  -movflags +faststart -an media/out.mp4
```

Both source pages open standalone in any browser — no build step:
`docs/showcase/showcase.html`, `docs/showcase/showcase-vertical.html`.
