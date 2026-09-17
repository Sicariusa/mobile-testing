# Showcase videos

Product films for the Mobile QA Test Runner, aimed at **mobile QA teams**. They
show what the runner does — runs your test cases hands-off, captures every
screen, and reports pass/fail — without exposing how the engine works.

| | format | length | audio | file |
|---|---|---|---|---|
| **Wide** (landscape / embeds) | 1920×1080 · 16:9 · 30fps | ~41s | yes | `mobile-qa-showcase.mp4` |
| **Vertical** (TikTok / Reels / Shorts) | 1080×1920 · 9:16 | ~43s | no | `mobile-qa-showcase-vertical.mp4` |

![poster](mobile-qa-showcase-poster.png)

H.264 (yuv420p, faststart) + AAC. Posters:
`mobile-qa-showcase-poster.png`, `mobile-qa-showcase-vertical-poster.png`.

## Wide cut

1. **Hook** — *"The QA agent for mobile apps."*
2. **Automated regression run** — five test cases execute hands-off. The phone
   is **locked to the running case**: a `case N of 5` counter and progress bar
   advance in step, the running row is highlighted, and the phone shows that
   case's screen with a `▶ Running · <case>` label (Login → Products → Cart →
   Checkout, where the expired card produces *"Payment declined"* → **FAIL** →
   Sign out). Screens are captured as it runs.
3. **Evidence** — *"Every screen, captured."* Before/after of every step.
4. **Report** — 4 passed / 1 failed, 80% pass rate, with the failed case
   expanded (*Expected "Order placed" ✓ / Got "Payment declined" ✕*).
5. **Close.**

## How it is built (and why it stays in sync)

The video is rendered from a self-contained animated page and screen-recorded,
then scored. Two wrinkles are handled explicitly:

- **Chromium renders the CSS timeline slower than wall-clock while recording.**
  `tools/measure_events.py` detects the five PASS/FAIL chips in the recording
  (they sit at known rects) and least-squares fits `video_t = a·anim_t + b`.
  Re-timing the video by `1/a` restores the authored pace, so cue times equal
  the animation times in the page. Measured fit: `a ≈ 1.1777`, max residual
  ≈ 0.05 s.
- **The soundtrack is generated, not licensed.** `tools/make_soundtrack.py`
  synthesises the bed (kick / hats / bass / arpeggio / pad over Am–F–C–G) plus
  UI sounds locked to the on-screen events. Verified sync: worst drift 67 ms
  (2 frames), most cues exact.

```bash
# 1. render
SHOW_MS=44000 node tools/record_showcase.mjs                 # → media/*.webm

# 2. measure the anim→video mapping
python3 tools/measure_events.py media/<recording>.webm

# 3. score it
python3 tools/make_soundtrack.py /tmp/soundtrack.wav

# 4. re-time to the authored pace and mux (a = scale_a from step 2)
ffmpeg -ss <offset_b> -i media/<recording>.webm -i /tmp/soundtrack.wav \
  -filter_complex "[0:v]setpts=(PTS-STARTPTS)/<a>,fps=30[v]" \
  -map "[v]" -map 1:a -t 41.3 \
  -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 19 -preset slow \
  -c:a aac -b:a 192k -movflags +faststart media/mobile-qa-showcase.mp4
```

Vertical cut:

```bash
SHOW_PAGE=docs/showcase/showcase-vertical.html VID_W=1080 VID_H=1920 SHOW_MS=42000 \
  node tools/record_showcase.mjs
```

Both source pages open standalone in any browser — no build step:
`docs/showcase/showcase.html`, `docs/showcase/showcase-vertical.html`.
