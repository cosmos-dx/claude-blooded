"""Speech-synced word timing shared by renderers: words light up where the voice actually speaks them,
so captions wait through dramatic pauses instead of drifting."""
from __future__ import annotations

import wave

import numpy as np


class VoiceActivity:
    RATE = 50   # analysis frames per second

    def __init__(self, voice_wav: str, threshold: float = 0.012):
        with wave.open(voice_wav) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        hop = sr // self.RATE
        n = len(x) // hop
        self.active = (np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) > threshold).astype(np.int8)
        self._cache: dict = {}

    def runs(self, a: float, b: float) -> list[tuple[float, float]]:
        act = self.active[int(a * self.RATE): int(b * self.RATE)]
        runs, cur = [], None
        for k, v in enumerate(act):
            if v and cur is None:
                cur = k
            if not v and cur is not None:
                runs.append([cur, k]); cur = None
        if cur is not None:
            runs.append([cur, len(act)])
        merged: list = []
        for r in runs:
            if merged and r[0] - merged[-1][1] < 18:      # close gaps under ~0.35 s (between syllables)
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        return [(a + r0 / self.RATE, a + r1 / self.RATE) for r0, r1 in merged] or [(a, b)]

    def word_times(self, line: dict) -> list[tuple[str, float, float]]:
        key = (line["start"], line["end"])
        if key in self._cache:
            return self._cache[key]
        words = line["text"].split()
        weights = [len(w) + 2 for w in words]
        total = sum(weights) or 1
        runs = self.runs(line["start"], line["end"])
        spoken = sum(b - a for a, b in runs)

        def at(u: float) -> float:
            acc = u * spoken
            for a, b in runs:
                if acc < b - a - 1e-6:
                    return a + acc
                acc -= b - a
            return runs[-1][1]
        out, pos = [], 0
        for w, k in zip(words, weights):
            out.append([w, at(pos / total), at((pos + k) / total)]); pos += k
        for (a0, b0), (a1, _) in zip(runs, runs[1:]):     # a word straddling a pause goes where its punctuation says
            for i, (w, s0, e0) in enumerate(out):
                if s0 <= b0 < e0 or (s0 < b0 + 0.01 and e0 > a1 - 0.01):
                    if i > 0 and out[i - 1][0][-1] in ".,?!:;…—":
                        out[i][1], out[i][2] = a1, max(e0, a1 + 0.15)
                    else:
                        out[i][2] = b0
                    break
        self._cache[key] = [tuple(x) for x in out]
        return self._cache[key]
