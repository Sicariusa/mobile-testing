#!/usr/bin/env python3
"""Synthesise the showcase soundtrack, locked to the video's own timeline.

The final video is time-corrected back to the authored animation pace (see
tools/measure_events.py), so cue times here are simply the animation seconds
used in docs/showcase/showcase.html.

Upbeat / energetic bed: kick, offbeat hats, bass, arpeggio and pad over an
Am-F-C-G progression, plus UI sounds locked to the on-screen events —
a blip when a case starts, a bright chime on PASS, a darker tone on FAIL,
shutter clicks on every screen capture.

Usage: python3 tools/make_soundtrack.py out.wav
"""
import sys
import wave

import numpy as np

SR = 48_000
DUR = 41.6                      # a touch past the 41.2s timeline
BPM = 124.0
BEAT = 60.0 / BPM               # 0.4839s
BAR = BEAT * 4

# ---- cue sheet (animation seconds — identical to the CSS timeline) ---------
HOOK_IN      = 0.30
GROOVE_IN    = 4.40             # run scene: drums enter
CASE_STARTS  = [5.40, 8.00, 10.40, 12.70, 15.50]
CASE_PASS    = [7.70, 10.10, 12.30, 17.50]
CASE_FAIL    = [15.20]
CAPTURES     = [7.70, 10.10, 12.30, 15.20, 17.50]     # shutter flash on phone
DECLINED     = 14.50
RUN_DONE     = 17.90
CAPTURE_IN   = 19.80
CAP_THUMBS   = [20.60, 20.90, 21.20, 21.50, 21.80, 22.10, 22.40, 22.70]
REPORT_IN    = 25.80
REPORT_HIT   = 26.05
REPORT_ROWS  = [26.70, 26.90, 27.10, 27.30, 27.50]
FAIL_DETAIL  = 27.90
CLOSE_IN     = 35.80
CLOSE_HIT    = 36.10
END          = 41.20

N = int(DUR * SR)
t = np.arange(N) / SR
left = np.zeros(N)
right = np.zeros(N)


def add(buf, start, sig, gain=1.0):
    i = int(start * SR)
    if i < 0:
        sig, i = sig[-i:], 0
    end = min(len(buf), i + len(sig))
    if end > i:
        buf[i:end] += sig[: end - i] * gain


def stereo(start, sig, gain=1.0, pan=0.0):
    """pan -1 = left, +1 = right"""
    l = gain * min(1.0, 1.0 - pan)
    r = gain * min(1.0, 1.0 + pan)
    add(left, start, sig, l)
    add(right, start, sig, r)


def env(n, attack, decay, curve=3.0):
    e = np.ones(n)
    a = max(1, int(attack * SR))
    d = max(1, int(decay * SR))
    e[:a] = np.linspace(0, 1, a)
    tail = np.linspace(0, 1, min(d, n))
    e[-len(tail):] *= (1 - tail) ** curve
    return e


def lowpass(x, cutoff):
    """one-pole lowpass"""
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def highpass(x, cutoff):
    return x - lowpass(x, cutoff)


# ---------------- instruments ----------------
def kick(dur=0.30):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = 48 + 90 * np.exp(-tt * 38)                     # pitch drop
    sig = np.sin(2 * np.pi * np.cumsum(f) / SR)
    sig *= np.exp(-tt * 12)
    click = (np.random.default_rng(1).standard_normal(n) * np.exp(-tt * 420)) * 0.25
    return np.tanh((sig + click) * 1.6) * 0.9


def hat(dur=0.06, bright=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(int(bright * 1000) + 7)
    sig = rng.standard_normal(n) * np.exp(-tt * 130)
    return highpass(sig, 6000 * bright) * 0.30


def bass(freq, dur):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    saw = 2 * ((tt * freq) % 1.0) - 1.0
    sig = lowpass(saw, 420) * env(n, 0.006, dur * 0.85, 2.0)
    return sig * 0.34


def pluck(freq, dur=0.34, gain=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    sig = (np.sin(2 * np.pi * freq * tt)
           + 0.45 * np.sin(2 * np.pi * freq * 2 * tt)
           + 0.18 * np.sin(2 * np.pi * freq * 3 * tt))
    return sig * np.exp(-tt * 7.5) * 0.16 * gain


def pad(freqs, dur, gain=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    sig = np.zeros(n)
    for k, f in enumerate(freqs):
        det = 1 + (0.003 * (k - 1))
        sig += np.sin(2 * np.pi * f * det * tt) + 0.5 * np.sin(2 * np.pi * f * 2 * det * tt)
    sig /= max(1, len(freqs)) * 1.5
    return sig * env(n, 0.5, dur * 0.5, 1.6) * 0.16 * gain


def chime(root=880.0, gain=1.0):
    """bright two-note PASS chime (a rising major third)"""
    out = np.zeros(int(0.85 * SR))
    for i, (f, off) in enumerate(((root, 0.0), (root * 1.26, 0.085))):
        n = int(0.7 * SR)
        tt = np.arange(n) / SR
        s = (np.sin(2 * np.pi * f * tt)
             + 0.5 * np.sin(2 * np.pi * f * 2.01 * tt)
             + 0.25 * np.sin(2 * np.pi * f * 3.02 * tt))
        s *= np.exp(-tt * 5.0)
        add(out, off, s, 0.16 * gain)
    return out


def fail_tone(gain=1.0):
    """darker, softer FAIL tone — noticeable, never harsh"""
    n = int(0.75 * SR)
    tt = np.arange(n) / SR
    s = (np.sin(2 * np.pi * 196 * tt)
         + 0.7 * np.sin(2 * np.pi * 233 * tt)          # minor-ish beating
         + 0.3 * np.sin(2 * np.pi * 98 * tt))
    return s * np.exp(-tt * 4.2) * 0.17 * gain


def blip(freq=980.0, gain=1.0):
    n = int(0.09 * SR)
    tt = np.arange(n) / SR
    return np.sin(2 * np.pi * freq * tt) * np.exp(-tt * 34) * 0.12 * gain


def shutter(gain=1.0):
    n = int(0.055 * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(23)
    s = rng.standard_normal(n) * np.exp(-tt * 190)
    return highpass(s, 2600) * 0.26 * gain


def whoosh(dur=0.7, gain=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(11)
    s = rng.standard_normal(n)
    s = highpass(lowpass(s, 2600), 320)
    shape = np.sin(np.pi * tt / dur) ** 2
    return s * shape * 0.20 * gain


def impact(gain=1.0):
    n = int(0.9 * SR)
    tt = np.arange(n) / SR
    body = np.sin(2 * np.pi * (70 + 40 * np.exp(-tt * 20)) * tt) * np.exp(-tt * 6)
    rng = np.random.default_rng(5)
    air = highpass(rng.standard_normal(n) * np.exp(-tt * 16), 1800) * 0.4
    return (body + air) * 0.28 * gain


# ---------------- arrangement ----------------
# Am - F - C - G, one chord per bar, grid starts at GROOVE_IN
CHORDS = [
    (110.00, [220.00, 261.63, 329.63]),   # Am
    (87.31,  [174.61, 220.00, 261.63]),   # F
    (130.81, [261.63, 329.63, 392.00]),   # C
    (98.00,  [196.00, 246.94, 293.66]),   # G
]

def section_gain(time):
    """how loud the drums are at a given moment"""
    if time < GROOVE_IN:      return 0.0
    if time < CAPTURE_IN:     return 1.0      # the run — full energy
    if time < REPORT_IN:      return 0.75     # capture — lighter
    if time < CLOSE_IN:       return 0.9      # report
    return 0.0                                # close — drums out

# pad runs the whole way, chords change each bar
bar_i = 0
tb = 0.0
while tb < END:
    root, tones = CHORDS[bar_i % 4]
    intro = tb < GROOVE_IN
    g = 0.75 if intro else (1.0 if tb < CLOSE_IN else 1.25)
    stereo(tb, pad(tones, BAR * 1.15, gain=g), 1.0, 0.0)
    bar_i += 1
    tb += BAR

# drums / bass / arp on the grid from GROOVE_IN
bar_i = 0
tb = GROOVE_IN
rng = np.random.default_rng(3)
while tb < CLOSE_IN:
    root, tones = CHORDS[bar_i % 4]
    dg = section_gain(tb)
    if dg > 0:
        for b in range(4):
            bt = tb + b * BEAT
            if bt >= CLOSE_IN:
                break
            light = section_gain(bt) < 0.8
            # kick: four-on-the-floor (1 & 3 only in the lighter section)
            if not light or b % 2 == 0:
                stereo(bt, kick(), 0.85 * dg, 0.0)
            # offbeat hat
            stereo(bt + BEAT / 2, hat(bright=1.0), 0.55 * dg, 0.12)
            if not light:
                stereo(bt + BEAT / 4, hat(dur=0.04, bright=1.3), 0.26 * dg, -0.15)
            # bass on 8ths
            stereo(bt, bass(root, BEAT * 0.9), 0.95 * dg, 0.0)
            stereo(bt + BEAT / 2, bass(root, BEAT * 0.45), 0.55 * dg, 0.0)
            # arpeggio 8ths through the chord
            stereo(bt, pluck(tones[b % 3] * 2, gain=0.9), 0.85 * dg, -0.25)
            stereo(bt + BEAT / 2, pluck(tones[(b + 1) % 3] * 2, gain=0.7), 0.7 * dg, 0.28)
    bar_i += 1
    tb += BAR

# intro shimmer before the drop
for k in range(4):
    stereo(2.0 + k * 0.55, pluck(CHORDS[0][1][k % 3] * 2, gain=0.55), 0.7, (-1) ** k * 0.3)

# ---------------- UI / event sounds ----------------
stereo(HOOK_IN, whoosh(0.9, gain=0.9), 1.0, 0.0)
stereo(GROOVE_IN - 0.55, whoosh(0.6, gain=1.15), 1.0, 0.0)     # riser into the run
stereo(GROOVE_IN, impact(0.85), 1.0, 0.0)

for s in CASE_STARTS:
    stereo(s, blip(980), 1.0, -0.1)

for p in CASE_PASS:
    stereo(p, chime(880), 1.0, 0.08)

for f in CASE_FAIL:
    stereo(f, fail_tone(), 1.0, 0.0)

stereo(DECLINED, blip(300, gain=1.3), 1.0, 0.0)                # uh-oh, before the FAIL

for c in CAPTURES:
    stereo(c, shutter(0.8), 1.0, 0.2)

# run complete — a small rising resolve
for i, f in enumerate((523.25, 659.25, 783.99)):
    stereo(RUN_DONE + i * 0.10, pluck(f, 0.5, gain=1.5), 1.0, 0.0)

stereo(CAPTURE_IN - 0.45, whoosh(0.55, gain=0.85), 1.0, 0.0)
for i, c in enumerate(CAP_THUMBS):
    stereo(c, shutter(0.85), 1.0, 0.3 if i % 2 else -0.3)

stereo(REPORT_IN - 0.5, whoosh(0.7, gain=1.1), 1.0, 0.0)
stereo(REPORT_HIT, impact(1.0), 1.0, 0.0)
for i, f in enumerate((261.63, 329.63, 392.00, 523.25)):        # C major spread
    stereo(REPORT_HIT + i * 0.055, pluck(f, 0.9, gain=1.6), 1.0, 0.0)
for r in REPORT_ROWS:
    stereo(r, blip(1180, gain=0.55), 1.0, 0.15)
stereo(FAIL_DETAIL, fail_tone(0.55), 1.0, 0.0)

# close — final chord
stereo(CLOSE_IN - 0.4, whoosh(0.7, gain=0.9), 1.0, 0.0)
stereo(CLOSE_HIT, impact(0.7), 1.0, 0.0)
for i, f in enumerate((220.00, 329.63, 440.00, 659.25)):
    stereo(CLOSE_HIT + i * 0.06, pluck(f, 1.6, gain=1.5), 1.0, 0.0)
stereo(CLOSE_HIT, pad([220.0, 329.63, 440.0], 4.6, gain=1.6), 1.0, 0.0)

# ---------------- master ----------------
fade = np.ones(N)
f_in = int(0.25 * SR)
fade[:f_in] = np.linspace(0, 1, f_in)
tail_start = int((END - 1.6) * SR)
if tail_start < N:
    fade[tail_start:] = np.linspace(1, 0, N - tail_start) ** 1.5
left *= fade
right *= fade

mix = np.stack([left, right], axis=1)
mix = np.tanh(mix * 1.05)                       # gentle soft-clip glue
peak = np.abs(mix).max()
if peak > 0:
    mix *= (10 ** (-1.0 / 20)) / peak           # normalise to -1 dBFS

pcm = (mix * 32767).astype(np.int16)
out = sys.argv[1] if len(sys.argv) > 1 else "soundtrack.wav"
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"wrote {out}  {DUR:.1f}s  peak={peak:.3f}")
