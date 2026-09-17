# Showcase video

A cinematic ~52s reel of the Mobile QA Test Runner.

![poster](mobile-qa-showcase-poster.png)

- **`mobile-qa-showcase.mp4`** — 1080p H.264 (yuv420p, faststart) for sharing.
- **`mobile-qa-showcase-poster.png`** — title/hero frame.

## Scenes

1. Title — *"It reads the screen like a human. It decides like a machine."*
2. The problem — selectors break, screens shift; so we test by **intent**.
3. Two-way perception — the accessibility **hierarchy** + **screenshot & OCR**.
4. A live run — a `PASS` with first-class step evidence (`resolved_by` /
   `validated_by` / recovery / learned selector).
5. The recovery ladder — retry → keyboard → dialog → scroll → bearing → OCR.
6. Stats — 6,897 lines of Python · 102 tests · 19 engine modules ·
   74% fewer device reads · 51s → 29s · no Android needed for CI.
7. Close — Deterministic · Self-healing · Evidence-first.

## Rebuild it

The video is rendered from a self-contained animated page and screen-recorded,
so it regenerates identically:

```bash
# source page: docs/showcase/showcase.html  (deterministic, time-based CSS)
node tools/record_showcase.mjs               # → media/mobile-qa-showcase.webm

# transcode to a shareable MP4 with any full ffmpeg build
ffmpeg -ss 0.5 -i media/mobile-qa-showcase.webm \
  -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 19 -preset slow \
  -movflags +faststart -an media/mobile-qa-showcase.mp4
```

`docs/showcase/showcase.html` opens in any browser on its own — no build step.
