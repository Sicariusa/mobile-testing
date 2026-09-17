#!/usr/bin/env python3
"""Measure when each PASS/FAIL chip actually appears in the rendered showcase.

Chromium renders the CSS timeline slightly slower than wall-clock while the
page is being screen-recorded, so animation time != video time. Rather than
guess the factor, we detect the five status chips directly (they sit at known
rects, see the LAYOUT NOTE in docs/showcase/showcase.html) and least-squares
fit  video_t = a * anim_t + b  from those five anchors. Every other audio cue
is then mapped through that fit, so the soundtrack lands on the right frames.

Usage:  python3 tools/measure_events.py <recording.webm>
Prints a JSON blob on stdout.
"""
import json
import subprocess
import sys

import numpy as np

FFMPEG = "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"

# Status-chip rects: row i top = 470 + (i-1)*64, status cell x = 339.
# Crop generously around each chip so a few px of layout drift can't miss it.
CHIP_X, CHIP_W, CHIP_H = 335, 92, 44
ROW_TOPS = [470, 534, 598, 662, 726]
# (anim second the chip pops, "pass" or "fail")
CHIPS = [(7.7, "pass"), (10.1, "pass"), (12.3, "pass"), (15.2, "fail"), (17.5, "pass")]


def region_series(path, x, y, w, h):
    """Average RGB of one rect, per frame, as an (N,3) float array."""
    cmd = [FFMPEG, "-v", "error", "-i", path,
           "-vf", f"crop={w}:{h}:{x}:{y},scale=1:1",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(float)


def frame_rate(path):
    out = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return 25.0  # Playwright records a constant 25fps


def first_sustained(sig, thresh, run=3):
    """First index where sig >= thresh and stays there for `run` frames."""
    ok = sig >= thresh
    for i in range(len(ok) - run):
        if ok[i:i + run].all():
            return i
    return None


def detect_chip(series, kind):
    r, g, b = series[:, 0], series[:, 1], series[:, 2]
    # colour-opponent signal: the chip is clearly green (PASS) or red (FAIL)
    sig = (g - (r + b) / 2) if kind == "pass" else (r - (g + b) / 2)
    base = np.median(sig[: max(10, len(sig) // 8)])
    span = sig.max() - base
    if span < 3:                      # nothing ever appeared here
        return None, span
    idx = first_sustained(sig, base + span * 0.55)
    return idx, span


def main(path):
    fps = frame_rate(path)
    anchors_anim, anchors_vid, report = [], [], []
    for (anim_t, kind), top in zip(CHIPS, ROW_TOPS):
        s = region_series(path, CHIP_X, top + 10, CHIP_W, CHIP_H)
        idx, span = detect_chip(s, kind)
        if idx is None:
            report.append({"anim": anim_t, "kind": kind, "detected": None, "span": round(span, 2)})
            continue
        vid_t = idx / fps
        anchors_anim.append(anim_t)
        anchors_vid.append(vid_t)
        report.append({"anim": anim_t, "kind": kind, "video": round(vid_t, 3),
                       "frame": int(idx), "span": round(span, 2)})

    if len(anchors_anim) < 2:
        print(json.dumps({"error": "too few anchors detected", "chips": report}, indent=2))
        return 1

    a, b = np.polyfit(np.array(anchors_anim), np.array(anchors_vid), 1)
    resid = [round(float(a * t + b - v), 4) for t, v in zip(anchors_anim, anchors_vid)]

    print(json.dumps({
        "fps": fps,
        "scale_a": round(float(a), 5),
        "offset_b": round(float(b), 5),
        "max_abs_residual_s": round(float(max(abs(r) for r in resid)), 4),
        "residuals_s": resid,
        "chips": report,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
