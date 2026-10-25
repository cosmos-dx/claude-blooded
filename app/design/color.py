"""Colour maths: hex parsing, WCAG 2.x relative luminance and contrast, and the smallest lightness change
that makes a colour meet a contrast target while keeping the hue and saturation the designer chose."""
from __future__ import annotations

import colorsys
from typing import Sequence

RGB = tuple[int, int, int]
WHITE, BLACK = (255, 255, 255), (0, 0, 0)


def parse_hex(value: str) -> RGB:
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
        raise ValueError(f"not a hex colour: {value!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def to_hex(c: Sequence[int]) -> str:
    return "#%02X%02X%02X" % tuple(int(x) for x in c[:3])


def luminance(c: Sequence[int]) -> float:
    def ch(x: float) -> float:
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a: Sequence[int], b: Sequence[int]) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg: RGB, bg: RGB, target: float) -> RGB:
    """`fg` itself when it already meets `target` on `bg`; otherwise the nearest lighter or darker shade of it
    that does; white or black when no shade of that hue can."""
    if contrast(fg, bg) >= target:
        return fg
    h, l, s = colorsys.rgb_to_hls(*(x / 255 for x in fg))
    best: tuple[int, RGB] | None = None
    for direction in (1, -1):
        for step in range(1, 101):
            nl = l + direction * step / 100
            if not 0 <= nl <= 1:
                break
            cand = tuple(round(x * 255) for x in colorsys.hls_to_rgb(h, nl, s))
            if contrast(cand, bg) >= target:
                if best is None or step < best[0]:
                    best = (step, cand)          # type: ignore[assignment]
                break
    if best:
        return best[1]
    return max((WHITE, BLACK), key=lambda c: contrast(c, bg))


def is_dark(c: Sequence[int]) -> bool:
    return luminance(c) < 0.18
