"""Sound design for reel-tutor-01: synthesized dark-ambient bed + SFX, cued from the spec, ducked under the voice.

  pad        Am - F - C - G at 92 bpm, detuned stereo, low-passed at 1.4 kHz, slow swell
  kick       soft sine kick on every beat from the first chapter scene on
  whoosh     filtered noise sweep into every scene change
  think      a particle_word with countdown: pad dips to 35%, clock tick-tock every 0.5 s, kick stops
  impact     riser + sub drop on the scene right after the countdown (the reveal)
  glitch     short square-wave stutter when the third voice cuts in (two_party scenes)
  ducking    music follows the voice envelope down by up to 60%; music sits at 0.30 under the voice
Writes mix.wav (voice + music) and music_bed.wav (music + SFX only, for re-voicing).
"""
from __future__ import annotations

import json, os, wave

import numpy as np
from scipy.signal import butter, lfilter, sosfilt

END_HOLD = 1.5   # seconds of hold after the last line (matches the renderers)

SR = 48000


def _lp(x, f): return sosfilt(butter(2, f, "low", fs=SR, output="sos"), x)
def _hp(x, f): return sosfilt(butter(2, f, "high", fs=SR, output="sos"), x)
def _hz(m): return 440 * 2 ** ((m - 69) / 12)


def _place(buf, x, at, g=1.0):
    i = int(at * SR)
    if 0 <= i < len(buf):
        x = x[: len(buf) - i]; buf[i:i + len(x)] += x * g


def _write(path, L, R):
    st = np.stack([L, R], 1); st = st / max(1e-6, np.abs(st).max()) * 0.92
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


def build(workdir, spec=None):
    """`spec` defaults to <workdir>/spec.json; skills with their own spec format pass a scene list instead."""
    spec = spec or json.load(open(os.path.join(workdir, "spec.json")))
    tl = json.load(open(os.path.join(workdir, "timeline.json")))
    dur = tl["duration"] + END_HOLD
    N = int(dur * SR); t = np.arange(N) / SR
    rng = np.random.default_rng(3)
    by = {}
    for ln in tl["lines"]: by.setdefault(ln["scene"], []).append(ln)
    scenes = spec["scenes"]
    starts = [by[s["id"]][0]["start"] for s in scenes if s["id"] in by]
    think0 = impact = None
    for i, s in enumerate(scenes):
        if s["visual"]["type"] == "particle_word" and s["visual"].get("countdown") and i + 1 < len(scenes):
            think0, impact = by[s["id"]][-1]["end"], by[scenes[i + 1]["id"]][0]["start"]; break
    pulse = next((by[s["id"]][0]["start"] for s in scenes if s.get("chapter") is not None), 0.0)
    glitches = [ln["start"] for s in scenes if s["visual"]["type"] == "two_party" for ln in by[s["id"]] if ln["spk"] == "C"][:2]

    beat = 60 / 92; bar = beat * 4
    chords = [[57, 60, 64], [53, 57, 60], [48, 55, 64], [55, 59, 62]]
    padL, padR = np.zeros(N), np.zeros(N)
    for b in range(int(dur / bar) + 2):
        n = int((bar + 0.8) * SR); tt = np.arange(n) / SR
        e = np.ones(n); na = int(0.8 * SR); e[:na] = np.linspace(0, 1, na); e[-na:] *= np.linspace(1, 0, na)
        for m in chords[b % 4] + [chords[b % 4][0] - 12]:
            for det, buf in ((-0.12, padL), (0.12, padR)):
                _place(buf, sum(np.sin(2 * np.pi * _hz(m + det) * k * tt + k) / k ** 1.4 for k in range(1, 6)) * e * 0.05, max(0, b * bar - 0.4))
    padL, padR = _lp(padL, 1400), _lp(padR, 1400)
    g = (0.55 + 0.25 * np.sin(2 * np.pi * t / 23)) * (np.where((t > think0) & (t < impact), 0.35, 1.0) if think0 else 1.0)
    padL *= g; padR *= g

    drums = np.zeros(N)
    kt = np.arange(int(0.45 * SR)) / SR
    kick = np.sin(2 * np.pi * (48 * kt + 60 * (1 - np.exp(-kt * 30)) / 30)) * np.exp(-kt * 9)
    x = pulse
    while x < dur - 1.5:
        if not (think0 and think0 - 0.3 < x < impact): _place(drums, kick, x, 0.32 if not impact or x < impact else 0.4)
        x += beat

    sfx = np.zeros(N)
    for s0 in starts[1:]:
        n = int(0.5 * SR)
        _place(sfx, _lp(rng.standard_normal(n), 2500) * np.sin(np.linspace(0, np.pi, n)) ** 2, s0 - 0.3, 0.12)
    if think0:
        tk = np.arange(int(0.03 * SR)) / SR
        x, i = think0, 0
        while x < impact - 0.1:
            _place(sfx, np.sin(2 * np.pi * (2200 if i % 2 == 0 else 1500) * tk) * np.exp(-tk * 160), x, 0.35); x += 0.5; i += 1
        rn = int(1.4 * SR)
        _place(sfx, _hp(rng.standard_normal(rn), 800) * np.linspace(0, 1, rn) ** 2, impact - 1.4, 0.10)
        it = np.arange(int(1.6 * SR)) / SR
        _place(sfx, np.sin(2 * np.pi * (40 * it + 80 * (1 - np.exp(-it * 12)) / 12)) * np.exp(-it * 3)
               + _lp(rng.standard_normal(len(it)), 900) * np.exp(-it * 8) * 0.6, impact - 0.05, 0.5)
    gt = np.arange(int(0.35 * SR)) / SR
    glitch = _lp(np.sign(np.sin(2 * np.pi * 180 * gt)) * (rng.random(len(gt)) > 0.3) * np.exp(-gt * 6), 3000)
    for gs in glitches: _place(sfx, glitch, gs, 0.10)

    with wave.open(os.path.join(workdir, "voice.wav")) as w:
        v = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    voice = np.zeros(N); voice[: min(N, len(v))] = v[:N]
    venv = lfilter([0.002], [1, -0.998], np.abs(voice))
    duck = 1 - np.clip(venv / (venv.max() + 1e-9) * 2.2, 0, 0.6)
    fade = np.clip(np.minimum(t / 1.5, (dur - t) / 2.0), 0, 1)
    _write(os.path.join(workdir, "music_bed.wav"), (padL + drums) * fade * 0.8 + sfx, (padR + drums) * fade * 0.8 + sfx)
    _write(os.path.join(workdir, "mix.wav"), voice + ((padL + drums) * duck * fade + sfx) * 0.30, voice + ((padR + drums) * duck * fade + sfx) * 0.30)
