# Showcase videos

Two cuts of the Mobile QA Test Runner reel.

| | format | length | file |
|---|---|---|---|
| **Vertical** (TikTok / Reels / Shorts) | 1080×1920 · 9:16 | ~43s | `mobile-qa-showcase-vertical.mp4` |
| **Wide** (landscape) | 1920×1080 · 16:9 | ~52s | `mobile-qa-showcase.mp4` |

![poster](mobile-qa-showcase-vertical-poster.png)

Both are H.264 (yuv420p, faststart) and play everywhere. Posters:
`mobile-qa-showcase-vertical-poster.png`, `mobile-qa-showcase-poster.png`.

## Vertical cut (product film — no internals)

An Apple-styled film with the phone as a persistent hero. Benefit-led copy only —
it never shows how the engine works.

1. Title — *"Automated testing that sees your app the way people do."*
2. Meet the runner — *"It drives your whole app. On its own."*
3. Perception — *"Finds every control. Reads every word."*
4. Resilience — *"Something in the way? It finds another."* (obstruction clears)
5. Evidence — *"Every step, captured as proof."*
6. Confidence — *"Know it works. Every time."* (Welcome / `PASS`)
7. Close — Deterministic · Self-healing · Effortless.

## Wide cut (engineering deep-dive)

The original landscape reel that does walk through the mechanism (perception,
a live run with step evidence, the recovery ladder, repo stats). Keep it for
internal / technical audiences; use the vertical cut for public sharing.

## Rebuild either one

Rendered from a self-contained animated page and screen-recorded, so each
regenerates identically. The recorder is configurable via env vars:

```bash
# Vertical (9:16)
SHOW_PAGE=docs/showcase/showcase-vertical.html VID_W=1080 VID_H=1920 SHOW_MS=42000 \
  node tools/record_showcase.mjs           # → media/*.webm

# Wide (16:9) — the default
node tools/record_showcase.mjs

# transcode to a shareable MP4 with any full ffmpeg build (trim the black head)
ffmpeg -ss 0.5 -i media/<recording>.webm \
  -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 19 -preset slow \
  -movflags +faststart -an media/out.mp4
```

Both source pages open standalone in any browser — no build step:
`docs/showcase/showcase-vertical.html`, `docs/showcase/showcase.html`.
