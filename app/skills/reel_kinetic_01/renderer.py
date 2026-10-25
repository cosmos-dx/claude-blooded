"""reel-kinetic-01 renderer: flat color blocking, huge condensed type, tiny follow-ups, sticker objects,
hard color-wipe cuts that land on spoken words. Two canvases (LAYOUTS):

9:16 (1080x1920): brand + progress top-left · stickers above (y ≈ 300-560) · headline centred at y 1000
(≤ 900 px wide, ≤ 640 px tall) · spoken line and label under it · hazard tape y ≈ 1530.
16:9 (1920x1080): brand + progress top-left · headline left of centre · stickers in the right third ·
spoken line and label under the headline · tape along the bottom edge.

A designed look (spec.custom_palette from the Design Director) re-assigns beat colours so the dominant,
secondary and accent backgrounds hold their 60-30-10 share of screen time (app/design/ratio.py), and
spec.fonts / spec.sizes replace the default faces and the small-type scale.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core.ffmpeg import ffmpeg
from app.design.ratio import distribute
from app.skills.timing import VoiceActivity

FPS, SS = 30, 2
END_HOLD = 1.5
PALETTES = json.loads((Path(__file__).parent / "palettes.json").read_text())
LAYOUTS = {
    "9:16": {"size": (1080, 1920), "brand": (60, 150), "bar_y": 182, "sticker": (540, 430), "sticker_k": 1.0,
             "head": (540, 1000), "head_max": (900, 640), "line_w": 760, "label_dy": 150, "tape_y": 1530},
    "16:9": {"size": (1920, 1080), "brand": (80, 84), "bar_y": 112, "sticker": (1520, 520), "sticker_k": 0.85,
             "head": (760, 500), "head_max": (1080, 500), "line_w": 1000, "label_dy": 120, "tape_y": 1030},
}
DEFAULT_FONTS = {"display": "anton/400", "text": "jetbrains-mono/600", "label": "jetbrains-mono/600", "sticker": "archivo-black/400"}
DEFAULT_SIZES = {"caption": 22, "label": 22}
PUNCH = {"star", "burst", "tape"}            # stickers that mark a punchline: where the accent colour belongs
S: dict = {}
_F: dict = {}


def font(role: str, size: float):
    k = (S["fonts"][role], int(size))
    if k not in _F:
        root = os.environ.get("REEL_FONT_DIR", "/usr/share/fonts/reel")
        _F[k] = ImageFont.truetype(f"{root}/{S['fonts'][role]}.ttf", max(6, int(size)))
    return _F[k]


def ease(x): x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3
def back(x, s=2.2): x = max(0.0, min(1.0, x)); return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def load(workdir: str) -> None:
    spec = json.loads((Path(workdir) / "spec.json").read_text())
    tl = json.loads((Path(workdir) / "timeline.json").read_text())
    va = VoiceActivity(str(Path(workdir) / "voice.wav"))
    palette = spec.get("custom_palette") or PALETTES[spec.get("palette", "poster")]
    beats, times = [], []
    for li, line in enumerate(spec["lines"]):
        wt = va.word_times(tl["lines"][li])
        for b in line["beats"]:
            beats.append(b)
            times.append(wt[min(b.get("word", 0), len(wt) - 1)][1] if wt else tl["lines"][li]["start"])
    order = sorted(range(len(beats)), key=lambda i: times[i])
    beats, times = [beats[i] for i in order], [times[i] for i in order]
    dur = tl["duration"] + END_HOLD
    if spec.get("custom_palette"):               # 60-30-10 by screen time, accents on punchlines
        durs = [b - a for a, b in zip(times, times[1:] + [dur])]
        codes = distribute(durs, spec.get("split") or (60, 30, 10), ("ds", "sd", "ad"), [b.get("sticker") in PUNCH for b in beats])
        beats = [{**b, "pair": c} for b, c in zip(beats, codes)]
    S.clear()
    _F.clear()
    S.update(spec=spec, lines=tl["lines"], va=va, dur=dur, nf=int(round(dur * FPS)), beats=beats, times=times,
             pairs={n: tuple(tuple(c) for c in v) for n, v in palette["pairs"].items()}, _wd=workdir,
             L=LAYOUTS.get(spec.get("format", "9:16"), LAYOUTS["9:16"]),
             fonts={**DEFAULT_FONTS, **(spec.get("fonts") or {})}, sizes={**DEFAULT_SIZES, **(spec.get("sizes") or {})})


def big_text(d, text, fg, shadow, t_in, cx, cy, maxw, maxh):
    lines = text.upper().split("\n")
    size = 420
    while size > 60:
        f = font("display", size * SS)
        if max(d.textlength(l, font=f) / SS for l in lines) <= maxw and size * 0.98 * len(lines) <= maxh:
            break
        size -= 6
    sc = 1.0 + 0.22 * (1 - back(t_in / 0.28))
    total = size * 0.98 * len(lines)
    off = 11 * ease(t_in / 0.2)
    fz = font("display", max(10, size * sc) * SS)
    for i, l in enumerate(lines):
        y = cy - total / 2 + (i + 0.5) * size * 0.98
        for dx, col in ((off, shadow), (0, fg)):
            d.text(((cx + dx) * SS, (y + dx) * SS), l, font=fz, fill=col, anchor="mm")
    return cy + total / 2


def tiny(d, s, x, y, col, size=22, track=4, anchor="c"):
    f = font("label", size * SS)
    w = sum(d.textlength(ch, font=f) for ch in s) / SS + track * (len(s) - 1)
    x0 = x - w / 2 if anchor == "c" else x
    for ch in s:
        d.text((x0 * SS, y * SS), ch, font=f, fill=col, anchor="lm")
        x0 += d.textlength(ch, font=f) / SS + track


def sticker(d, kind, t, t_in, fg, acc, label):
    """Stickers are drawn in the 9:16 design space around (540, 430) and mapped into the layout's sticker zone."""
    L = S["L"]
    W = L["size"][0]
    (sx, sy), k = L["sticker"], L["sticker_k"]
    a = ease(t_in / 0.3)
    T = lambda x, y: ((sx + (x - 540) * k) * SS, (sy + (y - 430) * k) * SS)
    P = lambda pts: [T(x, y) for x, y in pts]
    box = lambda x0, y0, x1, y1: [*T(x0, y0), *T(x1, y1)]
    if kind == "zzz":
        for i, ch in enumerate("Zzz"):
            ph, sz = (t * 0.6 + i * 0.25) % 1, (110 - i * 28) * a * k
            if sz > 8:
                d.text(T(760 + i * 70, 470 - i * 80 - ph * 30), ch, font=font("sticker", sz * SS), fill=acc, anchor="mm")
    elif kind == "cross":
        r = 120 * a
        for s in (-1, 1):
            d.line(P([(540 - r, 430 - s * r), (540 + r, 430 + s * r)]), fill=acc, width=int(34 * SS * k))
    elif kind == "check":
        d.line(P([(440, 430), (510, 500), (650, 340)]), fill=acc, width=int(34 * SS * k * a + 1), joint="curve")
    elif kind == "star":
        n, rot = 14, t * 0.4
        r1, r2 = 150 * a, 108 * a
        if r1 > 4:
            d.polygon(P([(540 + (r1 if i % 2 == 0 else r2) * math.cos(rot + i * math.pi / n),
                          430 + (r1 if i % 2 == 0 else r2) * math.sin(rot + i * math.pi / n)) for i in range(2 * n)]), fill=acc)
            if label:
                d.text(T(540, 430), label.upper()[:6], font=font("sticker", 52 * a * k * SS + 1), fill=fg, anchor="mm")
    elif kind == "circle":
        r = (190 - 70 * ease((t_in - 0.4) / 1.5)) * a
        d.ellipse(box(540 - r, 440 - r, 540 + r, 440 + r), fill=acc)
    elif kind == "ring":
        for j in range(3):
            ph = (t * 0.7 + j / 3) % 1
            r = (50 + ph * 170) * a
            d.ellipse(box(540 - r, 430 - r, 540 + r, 430 + r), outline=acc, width=int(10 * SS * k * (1 - ph) + 1))
    elif kind == "arrow":
        x = 240 + 560 * a
        d.line(P([(200, 430), (x, 430)]), fill=acc, width=int(40 * SS * k))
        d.polygon(P([(x + 70, 430), (x - 20, 350), (x - 20, 510)]), fill=acc)
    elif kind == "burst":                        # rays behind the headline
        hx, hy = L["head"]
        for i in range(18):
            an = i / 18 * 2 * math.pi + t * 0.3
            r0, r1 = 160 * a * k, (420 + 40 * math.sin(t * 6 + i)) * a * k
            d.line([((hx + r0 * math.cos(an)) * SS, (hy + r0 * math.sin(an)) * SS),
                    ((hx + r1 * math.cos(an)) * SS, (hy + r1 * math.sin(an)) * SS)], fill=acc, width=int(16 * SS * k))
    elif kind == "tape":                         # full-width hazard tape, independent of the sticker zone
        y0 = L["tape_y"]
        yy = lambda xx: (xx + 40) / (W + 80) * 120
        Q = lambda pts: [(x * SS, y * SS) for x, y in pts]
        d.polygon(Q([(-40, y0), (W + 40, y0 - 120), (W + 40, y0 - 30), (-40, y0 + 90)]), fill=acc)
        for i in range(-2, W // 90 + 3):
            x = i * 90 + (t * 120) % 90
            d.polygon(Q([(x, y0 + 90 - yy(x)), (x + 45, y0 + 90 - yy(x + 45)), (x + 45, y0 - yy(x + 45)), (x, y0 - yy(x))]), fill=fg)
    elif kind == "stack":
        for i in range(5):
            e = ease((t_in - i * 0.08) / 0.25)
            y = 520 - i * 46 + (1 - e) * 200
            d.rectangle(box(410 - i * 6, y, 670 - i * 6, y + 34), fill=acc if i % 2 == 0 else fg)


def frame(fi: int) -> np.ndarray:
    t = fi / FPS
    L = S["L"]
    W, H = L["size"]
    times, beats, pairs = S["times"], S["beats"], S["pairs"]
    bi = max([i for i, bt in enumerate(times) if bt <= t + 0.02] or [0])
    b = beats[bi]
    bg, fg, acc = pairs.get(b["pair"]) or next(iter(pairs.values()))
    t_in = t - times[bi] if t >= times[bi] else 0.3
    prev = (pairs.get(beats[bi - 1]["pair"]) or (bg,))[0] if bi > 0 else bg
    im = Image.new("RGB", (W * SS, H * SS), prev)
    d = ImageDraw.Draw(im)
    wipe = ease(t_in / 0.14)
    d.rectangle([0, (H - H * wipe) * SS, W * SS, H * SS], fill=bg)
    if wipe > 0.6:
        kind, label = b.get("sticker", "none"), b.get("label", "")
        sticker(d, kind, t, t_in, fg, acc, label)
        (hx, hy), (mw, mh) = L["head"], L["head_max"]
        bottom = big_text(d, b["big"], fg, acc, t_in, hx, hy, mw, mh)
        line = None
        for x in S["lines"]:
            if x["start"] - 0.05 <= t < x["end"] + min(0.45, x["gap"] + 0.1):
                line = x
        if line:
            cs = S["sizes"]["caption"]
            f = font("text", cs * SS)
            rows, cur = [], ""
            for w in " ".join(w for w, a0, _ in S["va"].word_times(line) if a0 <= t).lower().split():
                if d.textlength((cur + " " + w).strip(), font=f) / SS > L["line_w"]:
                    rows.append(cur); cur = w
                else:
                    cur = (cur + " " + w).strip()
            if cur:
                rows.append(cur)
            for j, row in enumerate(rows[-2:]):
                d.text((hx * SS, (bottom + 60 + j * cs * 1.55) * SS), row, font=f, fill=fg, anchor="mm")
        if label and kind != "star":
            tiny(d, label.upper(), hx, bottom + L["label_dy"], fg, S["sizes"]["label"])
    bx, by = L["brand"]
    tiny(d, (S["spec"].get("brand") or "").upper()[:40], bx, by, fg, max(12, S["sizes"]["label"] - 4), 4, anchor="l")
    d.rectangle([bx * SS, L["bar_y"] * SS, (bx + (W - 2 * bx) * t / S["dur"]) * SS, (L["bar_y"] + 6) * SS], fill=fg)
    fade = max(0.0, min(1.0, t / 0.3, (S["dur"] - t) / 0.6))
    return (np.asarray(im.resize((W, H), Image.BOX), np.float32) * fade).clip(0, 255).astype(np.uint8)


def _chunk(args):
    wd, k, a, b, out = args
    if S.get("_wd") != wd:
        load(wd)
    W, H = S["L"]["size"]
    pr = subprocess.Popen(ffmpeg("-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", out), stdin=subprocess.PIPE)
    for fi in range(a, b):
        pr.stdin.write(frame(fi).tobytes())
    pr.stdin.close()
    if pr.wait() != 0:
        raise RuntimeError(f"ffmpeg failed on chunk {k}")
    return k


def render(workdir: str, progress=lambda f: None, processes: int = 1) -> None:
    load(workdir)
    n = max(1, processes)
    edges = np.linspace(0, S["nf"], n * 4 + 1).astype(int)
    cdir = Path(workdir) / "kchunks"
    cdir.mkdir(exist_ok=True)
    jobs = [(workdir, i, int(edges[i]), int(edges[i + 1]), str(cdir / f"c{i:03d}.mp4")) for i in range(len(edges) - 1)]
    done = 0
    if n == 1:                       # small machines: no process pool, no extra memory
        for j in jobs:
            _chunk(j); done += 1; progress(done / len(jobs))
    else:
        with Pool(n) as pool:
            for _ in pool.imap_unordered(_chunk, jobs):
                done += 1; progress(done / len(jobs))
    (cdir / "list.txt").write_text("".join(f"file '{j[4]}'\n" for j in jobs))
    subprocess.run(ffmpeg("-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(cdir / "list.txt"), "-c", "copy",
                          str(Path(workdir) / "video_silent.mp4")), check=True)
    for p in cdir.iterdir():
        p.unlink()
    cdir.rmdir()
