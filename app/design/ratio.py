"""60-30-10 over time: which colour pair each beat of a reel gets, so the dominant, secondary and accent
backgrounds hold their share of screen time."""
from __future__ import annotations

from typing import Sequence


def distribute(durations: Sequence[float], split: Sequence[float] = (60, 30, 10),
               codes: Sequence[str] = ("ds", "sd", "ad"), punch: Sequence[bool] = ()) -> list[str]:
    """Pair code per beat. The accent (last code) goes to punchline beats (`punch`) while it stays within its
    share, with at least one accent beat (the last punchline, else the final beat). The rest is greedy on the
    remaining shares, avoiding the same colour back-to-back so every cut still reads as a cut."""
    n = len(durations)
    if n == 0:
        return []
    total = float(sum(durations)) or 1.0
    share = [s / float(sum(split)) for s in split]
    out: list[str | None] = [None] * n

    accent_budget = share[-1] * total
    used_accent = 0.0
    hinted = [i for i in range(n) if i < len(punch) and punch[i]]
    for i in hinted:
        if used_accent + durations[i] <= accent_budget * 1.5 or used_accent == 0:
            out[i] = codes[-1]
            used_accent += durations[i]
    if used_accent == 0:
        out[n - 1] = codes[-1]

    base, base_share = list(codes[:-1]), [s / (1 - share[-1]) for s in share[:-1]]
    used, elapsed = [0.0] * len(base), 0.0
    for i in range(n):
        if out[i] is not None:
            continue
        prev, d = (out[i - 1] if i else None), durations[i]

        def score(k: int) -> float:              # running deficit, so colours interleave (D D S D D S ...)
            return base_share[k] * (elapsed + d) - used[k] - (0.3 * d if base[k] == prev else 0.0)
        k = max(range(len(base)), key=score)
        out[i] = base[k]
        used[k] += d
        elapsed += d
    return [c for c in out if c is not None]


def shares(codes: Sequence[str], durations: Sequence[float]) -> dict[str, float]:
    """Actual screen-time share per code (for logs and tests)."""
    total = float(sum(durations)) or 1.0
    out: dict[str, float] = {}
    for c, d in zip(codes, durations):
        out[c] = out.get(c, 0.0) + d / total
    return {c: round(v, 3) for c, v in out.items()}
