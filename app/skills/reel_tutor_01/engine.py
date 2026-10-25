"""reel-tutor-01 renderer: spec.json + theme.json + timeline.json + voice.wav -> video_silent.mp4.

1080x1920 @ 30fps. Layout (top -> bottom): header + progress ruler (y 150-190) · captions (y 240-360)
· chapter rail of 3D wire cubes (y 450-720) · bracketed panel with a mono tag (y 830-1440) · empty
below (Instagram's UI covers it). Scenes are chosen from the element library at the bottom.

Drawing: vector layer at 2x, box-downsampled (anti-aliased hairlines); particles splatted with numpy;
faint bloom; then the theme's gradient map recolors ink luminance + the accent channel.
"""
from __future__ import annotations

import json, math, os, subprocess, wave, zlib
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.ffmpeg import ffmpeg

W, H, FPS, SS = 1080, 1920, 30, 2
END_HOLD = 1.5
WHITE = (238, 238, 236); G1 = (168, 168, 166); G2 = (112, 112, 110); G3 = (66, 66, 66); G4 = (34, 34, 34)
BLACK = (0, 0, 0); RED = (232, 84, 76)
COLORS = {"white": WHITE, "red": RED, "grey": G1}
S = {}   # per-process state: spec, theme, windows, envelope ...


def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_io(x): x = clamp(x); return x * x * (3 - 2 * x)
def rgba(c, a=1.0): return (*c[:3], int(clamp(a) * 255))
def lerp(a, b, t): return a + (b - a) * t


# ---------------------------------------------------------------- fonts (family comes from the theme)
FONT_DIR = os.environ.get("REEL_FONT_DIR", os.path.expanduser("~/.cache/reel-tutor-01/fonts"))
WEIGHTS = {"Light": 300, "Regular": 400, "Medium": 500, "Semibold": 600, "Bold": 700, "Black": 900}
_F = {}


def _font_file(family, weight):
    d = os.path.join(FONT_DIR, family)
    if not os.path.isdir(d): return None
    have = sorted(int(f[:-4]) for f in os.listdir(d) if f[:-4].isdigit())
    if not have: return None
    w = min(have, key=lambda x: (abs(x - WEIGHTS[weight]), -x))
    return os.path.join(d, f"{w}.ttf")


def F(kind, size, weight="Regular"):
    fam = S.get("fonts", {}).get(kind, "inter" if kind == "sans" else "jetbrains-mono")
    k = (fam, int(size), weight)
    if k not in _F:
        path = _font_file(fam, weight)
        if path:
            _F[k] = ImageFont.truetype(path, max(6, int(size)))
        else:   # macOS fallback: SF Pro / SF Mono variable fonts
            f = ImageFont.truetype("/System/Library/Fonts/" + ("SFNSMono.ttf" if kind == "mono" else "SFNS.ttf"), max(6, int(size)))
            f.set_variation_by_name("Bold" if (kind == "mono" and weight == "Black") else weight)
            _F[k] = f
    return _F[k]


# glyphs missing from the latin font subsets
GLYPHS = str.maketrans({"→": "->", "←": "<-", "✓": "", "✔": "", "✕": "x", "✗": "x", "•": "·", "≥": ">=", "≤": "<="})


# ---------------------------------------------------------------- canvas
_KER = {}


def kernel(r):
    if r not in _KER:
        h = int(math.ceil(r * 1.6))
        yy, xx = np.mgrid[-h:h + 1, -h:h + 1]
        k = np.exp(-(xx ** 2 + yy ** 2) / (2 * (r * 0.62) ** 2))
        _KER[r] = (h, [(dy, dx, k[dy + h, dx + h]) for dy in range(-h, h + 1) for dx in range(-h, h + 1) if k[dy + h, dx + h] > 0.04])
    return _KER[r]


class Cv:
    def __init__(self):
        self.v = Image.new("RGB", (W * SS, H * SS), (2, 2, 3))
        self.d = ImageDraw.Draw(self.v, "RGBA")
        self.idx, self.wts, self.ridx, self.rwts = [], [], [], []

    def line(self, pts, col=G1, w=1.5, a=1.0):
        if a <= 0.004: return
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=rgba(col, a), width=max(1, int(round(w * SS))), joint="curve")

    def dline(self, p0, p1, col=G2, w=1.5, a=1.0, dash=10, gap=8, phase=0.0):
        (x0, y0), (x1, y1) = p0, p1
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1 or a <= 0.004: return
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        s = -((phase * (dash + gap)) % (dash + gap))
        while s < L:
            a0, a1 = max(0, s), min(L, s + dash)
            if a1 > a0: self.line([(x0 + ux * a0, y0 + uy * a0), (x0 + ux * a1, y0 + uy * a1)], col, w, a)
            s += dash + gap

    def circle(self, cx, cy, r, fill=None, outline=None, w=1.5, a=1.0):
        if a <= 0.004 or r <= 0: return
        self.d.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], fill=rgba(fill, a) if fill else None,
                       outline=rgba(outline, a) if outline else None, width=max(1, int(round(w * SS))))

    def arc(self, cx, cy, r, a0, a1, col=WHITE, w=2, a=1.0):
        self.d.arc([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], a0, a1, fill=rgba(col, a), width=max(1, int(w * SS)))

    def rect(self, box, r=0, fill=None, outline=None, w=1.5, a=1.0):
        x0, y0, x1, y1 = box
        if x1 - x0 < 1 or y1 - y0 < 1 or a <= 0.004: return
        r = max(0, min(r, (x1 - x0) / 2 - 1, (y1 - y0) / 2 - 1))
        self.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], int(r * SS), fill=rgba(fill, a) if fill else None,
                                 outline=rgba(outline, a) if outline else None, width=max(1, int(round(w * SS))))

    def poly(self, pts, fill=None, outline=None, a=1.0, w=1.5):
        if a <= 0.004: return
        P = [(x * SS, y * SS) for x, y in pts]
        if fill: self.d.polygon(P, fill=rgba(fill, a))
        if outline: self.d.line(P + [P[0]], fill=rgba(outline, a), width=max(1, int(round(w * SS))), joint="curve")

    def tw(self, s, kind, size, weight="Regular", track=0):
        s = s.translate(GLYPHS)
        return self.d.textlength(s, font=F(kind, size * SS, weight)) / SS + track * max(0, len(s) - 1)

    def text(self, x, y, s, kind="sans", size=30, col=WHITE, weight="Regular", anchor="l", a=1.0, track=0):
        s = s.translate(GLYPHS)
        wdt = self.tw(s, kind, size, weight, track)
        if a <= 0.004: return wdt
        f = F(kind, size * SS, weight)
        if anchor == "c": x -= wdt / 2
        elif anchor == "r": x -= wdt
        if track == 0:
            self.d.text((x * SS, y * SS), s, font=f, fill=rgba(col, a), anchor="lm")
        else:
            for ch in s:
                self.d.text((x * SS, y * SS), ch, font=f, fill=rgba(col, a), anchor="lm")
                x += self.d.textlength(ch, font=f) / SS + track
        return wdt

    def fit(self, s, kind, size, weight, maxw, track=0):
        while size > 12 and self.tw(s, kind, size, weight, track) > maxw:
            size -= 1
        return size

    def splat(self, x, y, v, r=1.2, red=False):
        h, offs = kernel(r)
        xi = np.round(x).astype(np.int64); yi = np.round(y).astype(np.int64)
        m = (xi >= h) & (xi < W - h) & (yi >= h) & (yi < H - h) & (v > 0.003)
        xi, yi, v = xi[m], yi[m], v[m]
        base = yi * W + xi
        I, Wt = (self.ridx, self.rwts) if red else (self.idx, self.wts)
        for dy, dx, k in offs:
            I.append(base + dy * W + dx); Wt.append(v * k)

    def finish(self, fade=1.0):
        arr = np.asarray(self.v.resize((W, H), Image.BOX), np.float32)
        for idx, wts, col in ((self.idx, self.wts, (236, 236, 234)), (self.ridx, self.rwts, RED)):
            if idx:
                p = np.bincount(np.concatenate(idx), np.concatenate(wts), minlength=W * H).reshape(H, W)
                arr += np.minimum(p, 1.4)[..., None] * np.array(col, np.float32)
        arr = np.clip(arr, 0, 255)
        th = S["theme_rt"]
        if th["glow"] > 0:
            small = Image.fromarray(arr.astype(np.uint8)).resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5))
            arr += np.asarray(small.resize((W, H), Image.BILINEAR), np.float32) * th["glow"]
        return apply_theme(arr, fade)


# ---------------------------------------------------------------- theme: recolor ink luminance + accent
def theme_runtime(t: dict):
    xs = np.linspace(0, 1, 512)
    stops = t["stops"]
    lut = np.stack([np.interp(xs, [p for p, _ in stops], [c[i] for _, c in stops]) for i in range(3)], 1).astype(np.float32)
    accent_delta = np.array(t["accent"], np.float32) - lut[int(min(RED) / 255 * 511)]
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    bg = t.get("background", "solid")
    if bg == "vignette":
        d = np.sqrt(((x - W / 2) / W) ** 2 + ((y - H * 0.42) / H) ** 2 * 0.7)
        pat = np.clip(1 - d * 1.7, 0, 1) ** 2 * 26
    elif bg == "grid":
        pat = (((x % 60) < 1.5) | ((y % 60) < 1.5)).astype(np.float32) * 9
    elif bg == "dots":
        pat = (((x % 48) < 2) & ((y % 48) < 2)).astype(np.float32) * 22
    elif bg == "gradient":
        pat = (1 - y / H) * 18
    else:
        pat = np.zeros((H, W), np.float32)
    return dict(lut=lut, accent_delta=accent_delta, pattern=pat, glow=float(t.get("glow", 0.32)), grain=float(t.get("grain", 0.0)))


def apply_theme(arr, fade):
    th = S["theme_rt"]
    lum = arr.min(axis=2)
    red = np.clip((arr[..., 0] - lum) / (RED[0] - min(RED)), 0, 1.3)
    lum = lum * fade + th["pattern"]
    if th["grain"] > 0:
        lum = lum + np.random.default_rng().normal(0, 6 * th["grain"], (H, W)).astype(np.float32)
    out = th["lut"][np.clip(lum * (511 / 255), 0, 511).astype(np.int32)] + red[..., None] * fade * th["accent_delta"]
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- 3D
class Cam:
    def __init__(self, yaw, pitch, dist, f, cx, cy):
        self.cy_, self.sy = math.cos(yaw), math.sin(yaw)
        self.cp, self.sp = math.cos(pitch), math.sin(pitch)
        self.dist, self.f, self.cx, self.cyy = dist, f, cx, cy

    def p(self, X):
        X = np.asarray(X, np.float64).reshape(-1, 3)
        x, y, z = X[:, 0], X[:, 1], X[:, 2]
        x2 = x * self.cy_ + z * self.sy; z2 = -x * self.sy + z * self.cy_
        y2 = y * self.cp - z2 * self.sp; z3 = y * self.sp + z2 * self.cp + self.dist
        return np.stack([self.cx + self.f * x2 / z3, self.cyy - self.f * y2 / z3], 1)

    def pt(self, x, y, z):
        P = self.p([[x, y, z]])
        return float(P[0, 0]), float(P[0, 1])


EDGES = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
FACES = [((0, 1, 3, 2), 0.55), ((4, 6, 7, 5), 0.8), ((0, 4, 5, 1), 0.65), ((2, 3, 7, 6), 0.65), ((0, 2, 6, 4), 0.95), ((1, 5, 7, 3), 0.7)]


def box_verts(cx, cy, cz, sx, sy, sz):
    return np.array([[cx + dx * sx / 2, cy + dy * sy / 2, cz + dz * sz / 2] for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)])


def wire_box(c, cam, cx, cy, cz, sx, sy, sz, col=G1, w=1.5, a=1.0, fill=0.0, fillcol=WHITE, dashed=False):
    P = cam.p(box_verts(cx, cy, cz, sx, sy, sz))
    if fill > 0:
        for f, shade in FACES:
            pts = [tuple(P[i]) for i in f]
            area = sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))
            if area < 0: c.poly(pts, fill=tuple(int(v * shade) for v in fillcol), a=a * fill)
    for i, j in EDGES:
        if dashed: c.dline(tuple(P[i]), tuple(P[j]), col, w, a, dash=6, gap=6)
        else: c.line([tuple(P[i]), tuple(P[j])], col, w, a)


# ---------------------------------------------------------------- particles
NP = 3000
RNG = np.random.default_rng(11)
BRIGHT = RNG.uniform(0.45, 1.0, NP)
RAD = RNG.choice([1.0, 1.3, 1.7, 2.2], NP, p=[0.35, 0.3, 0.22, 0.13])
DELAY = RNG.uniform(0, 0.35, NP)
PERM = RNG.permutation(NP)
SHAPES = {}


def fib_sphere(n, seed=1):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n); th = np.pi * (1 + 5 ** 0.5) * i
    P = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)
    return P * (1 + np.random.default_rng(seed).normal(0, 0.018, (n, 1)))


def text_points(s, n=NP, width=860, seed=0):
    f = F("sans", 240, "Black")
    bb = ImageDraw.Draw(Image.new("L", (10, 10))).textbbox((0, 0), s, font=f)
    w, h = bb[2] - bb[0] + 20, bb[3] - bb[1] + 20
    im = Image.new("L", (w, h)); ImageDraw.Draw(im).text((10 - bb[0], 10 - bb[1]), s, font=f, fill=255)
    ys, xs = np.nonzero(np.asarray(im) > 140)
    rng = np.random.default_rng(seed)
    k = rng.choice(len(xs), n, replace=len(xs) < n)
    x = xs[k] - w / 2 + rng.uniform(-0.6, 0.6, n); y = ys[k] - h / 2 + rng.uniform(-0.6, 0.6, n)
    sc = min(width / w, 520 / h) if len(s) > 1 else 700 / h
    return np.stack([x * sc, -y * sc, rng.normal(0, 7, n)], 1)


def shape(word):
    if word not in SHAPES:
        SHAPES[word] = text_points(word, seed=zlib.crc32(word.encode()) % 1000)   # stable across processes
    return SHAPES[word]


def draw_points(c, P, cx, cy, yaw=0.0, pitch=0.0, f=1600, a=1.0, red=False):
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
    y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
    k = f / (f + z)
    v = BRIGHT[: len(P)] * np.clip(0.8 - 0.35 * (z / 300.0), 0.3, 1.0) * a * 1.25
    rad = RAD[: len(P)]
    for r in (1.0, 1.3, 1.7, 2.2):
        m = rad == r
        if m.any(): c.splat((cx + x * k)[m], (cy - y * k)[m], v[m], r=r, red=red)


def morph(t, t0, dur, A, B):
    u = np.clip(np.clip((t - t0) / dur - DELAY, 0, 1) / 0.65, 0, 1)
    return A + (B - A) * (u * u * (3 - 2 * u))[:, None]


def orb(c, cx, cy, R, t, amp, a=1.0, ring=True, n=None, red=False):
    P = SHAPES["unit_sphere"]
    lat = np.arcsin(np.clip(P[:, 2], -1, 1)); lon = np.arctan2(P[:, 1], P[:, 0])
    rr = 1 + (0.02 + 0.16 * amp) * np.sin(6 * lon + 4 * lat - t * 7) * np.cos(lat) + 0.015 * np.sin(3 * lat + t * 2)
    Q = (P * rr[:, None] * R)[:, [0, 2, 1]]
    if n: Q = Q[PERM[:n]]
    x, y, z = Q[:, 0], Q[:, 1], Q[:, 2]
    yaw, pitch = t * 0.32, 0.35
    x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
    y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
    k = 1600 / (1600 + z)
    v = BRIGHT[: len(Q)] * np.clip(0.6 - 0.5 * z / (abs(z).max() + 1e-6), 0.12, 1.0) * a
    rad = RAD[: len(Q)]
    for r in (1.0, 1.3, 1.7, 2.2):
        m = rad == r
        if m.any(): c.splat((cx + x * k)[m], (cy - y * k)[m], v[m], r=r, red=red)
    if ring:
        c.line([(cx + math.cos(i / 96 * 2 * math.pi) * R * 1.32, cy + math.sin(i / 96 * 2 * math.pi) * R * 0.17) for i in range(97)], G3, 1.2, a)


# ---------------------------------------------------------------- load
def load(workdir):
    spec = json.load(open(os.path.join(workdir, "spec.json")))
    tp = os.path.join(workdir, "theme.json")
    theme = json.load(open(tp)) if os.path.exists(tp) else {"stops": [(0.0, [2, 2, 3]), (1.0, [250, 250, 248])], "accent": list(RED)}
    S["fonts"] = {"sans": theme.get("sans", "inter"), "mono": theme.get("mono", "jetbrains-mono")}
    S["theme_rt"] = theme_runtime(theme)
    _F.clear(); SHAPES.clear(); _WT.clear()
    tl = json.load(open(os.path.join(workdir, "timeline.json")))
    dur = tl["duration"] + END_HOLD; nf = int(round(dur * FPS))
    wins = []
    for ln in tl["lines"]:
        if not wins or wins[-1][0] != ln["scene"]:
            wins.append([ln["scene"], ln["start"] - 0.15 if wins else 0.0, None])
    for i in range(len(wins) - 1): wins[i][2] = wins[i + 1][1]
    wins[-1][2] = dur
    S.update(spec=spec, lines=tl["lines"], dur=dur, nf=nf, wins=wins, scene_by_id={s["id"]: s for s in spec["scenes"]},
             lines_by_scene={}, keywords={k.lower() for k in spec.get("keywords", [])})
    for ln in tl["lines"]: S["lines_by_scene"].setdefault(ln["scene"], []).append(ln)
    with wave.open(os.path.join(workdir, "voice.wav")) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    hop = sr // FPS
    a = np.pad(x, (0, max(0, nf * hop - len(x))))[: nf * hop]
    rms = np.sqrt(np.mean(a.reshape(nf, hop) ** 2, axis=1)); rms = rms / (np.percentile(rms, 97) + 1e-6)
    env = np.zeros(nf, np.float32); v = 0.0
    for i, r in enumerate(np.clip(rms, 0, 1.3)):
        v += (r - v) * (0.5 if r > v else 0.12); env[i] = v
    hop50 = sr // 50; n50 = len(x) // hop50
    S["env"] = env
    S["active"] = (np.sqrt(np.mean(x[: n50 * hop50].reshape(n50, hop50) ** 2, axis=1)) > 0.012).astype(np.int8)
    SHAPES["unit_sphere"] = fib_sphere(NP); SHAPES["sphere"] = SHAPES["unit_sphere"] * 330
    SHAPES["cloud"] = np.random.default_rng(5).normal(0, 1, (NP, 3)) * np.array([520, 700, 300])
    for s in spec["scenes"]:
        if s["visual"]["type"] in ("particle_word", "comment"): shape(particle_word(s))
    n = max(1, len(spec.get("chapters", [])))
    S["rail_cam"] = Cam(-0.11, 0.30, 11.5, min(1500, 920 * 11.5 / (n + 0.8)), W / 2 + 6, 600)
    blocks = []
    for name, a0, b0 in wins:
        if S["scene_by_id"][name].get("chapter") is not None:
            if blocks and abs(blocks[-1][1] - a0) < 1e-6: blocks[-1][1] = b0
            else: blocks.append([a0, b0])
    S["rail_blocks"] = blocks


def particle_word(s):
    return (s["visual"].get("word") or ("YOUR TURN" if s["visual"]["type"] == "comment" else "?"))[:14]


def scene_at(t):
    for name, a, b in S["wins"]:
        if a <= t < b: return name, t - a, b - a
    name, a, b = S["wins"][-1]
    return name, t - a, b - a


def scene_window(name):
    return next((a, b) for n, a, b in S["wins"] if n == name)


def prev_scene(name):
    ids = [n for n, _, _ in S["wins"]]
    i = ids.index(name)
    return S["scene_by_id"][ids[i - 1]] if i > 0 else None


def reveal(lt, sd, i, n, item=None, span=0.8, start=0.08):
    at = item.get("at") if item and item.get("at") is not None else start + span * i / max(1, n)
    return ease((lt - at * sd) / 0.4)


# ---------------------------------------------------------------- captions (word timing follows the real speech)
_WT = {}


def speech_runs(a, b):
    act = S["active"][int(a * 50): int(b * 50)]
    runs, cur = [], None
    for k, v in enumerate(act):
        if v and cur is None: cur = k
        if not v and cur is not None: runs.append([cur, k]); cur = None
    if cur is not None: runs.append([cur, len(act)])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < 18: merged[-1][1] = r[1]
        else: merged.append(r)
    return [(a + r0 / 50, a + r1 / 50) for r0, r1 in merged] or [(a, b)]


def word_times(ln):
    key = (ln["start"], ln["end"])
    if key in _WT: return _WT[key]
    words = ln["text"].split(); wts = [len(w) + 2 for w in words]; tot = sum(wts)
    runs = speech_runs(ln["start"], ln["end"]); sl = sum(b - a for a, b in runs)

    def at(u):
        acc = u * sl
        for a, b in runs:
            if acc < b - a - 1e-6: return a + acc
            acc -= b - a
        return runs[-1][1]
    out, cpos = [], 0
    for w, k in zip(words, wts):
        out.append([w, at(cpos / tot), at((cpos + k) / tot)]); cpos += k
    for (a0, b0), (a1, b1) in zip(runs, runs[1:]):   # a word straddling a pause goes where its punctuation says
        for i, (w, s0, e0) in enumerate(out):
            if s0 <= b0 < e0 or (s0 < b0 + 0.01 and e0 > a1 - 0.01):
                if i > 0 and out[i - 1][0][-1] in ".,?!:;…—": out[i][1], out[i][2] = a1, max(e0, a1 + 0.15)
                else: out[i][2] = b0
                break
    _WT[key] = [tuple(x) for x in out]
    return _WT[key]


def captions(c, t):
    ln = None
    for x in S["lines"]:
        if x["start"] - 0.05 <= t < x["end"] + min(0.45, x["gap"] + 0.1): ln = x
    if not ln: return
    chs, cur, n = [], [], 0
    for w in word_times(ln):
        cur.append(w); n += len(w[0]) + 1
        if n > 40 or (w[0][-1] in ".?!" and n > 16): chs.append(cur); cur, n = [], 0
    if cur: chs.append(cur)
    ch = chs[0]
    for x in chs:
        if t >= x[0][1] - 0.05: ch = x
    size, wt = 50, "Semibold"
    lines, cur = [], []
    for w in ch:
        if cur and c.tw(" ".join(x[0] for x in cur + [w]), "sans", size, wt) > 990: lines.append(cur); cur = []
        cur.append(w)
    lines.append(cur)
    if len(lines) > 2: size = 42
    yc = 300 if len(lines) == 1 else 270
    fade = ease((t - ch[0][1] + 0.08) / 0.18)
    if ln["spk"] != "N":
        names = S["spec"].get("speakers") or {}
        lab = names.get(ln["spk"]) or ("SECOND VOICE" if ln["spk"] == "R" else "THIRD VOICE")
        c.text(W / 2, 236, lab.upper() + " —", "mono", 18, G1, "Semibold", "c", fade, track=3)
    for li, row in enumerate(lines):
        s = " ".join(x[0] for x in row)
        x = W / 2 - c.tw(s, "sans", size, wt) / 2
        y = yc + li * (size + 12)
        for w, a0, a1 in row:
            col = WHITE if t >= a0 else (72, 72, 72)
            if a0 <= t < a1: col = tuple(int(lerp(72, v, ease((t - a0) / max(0.05, a1 - a0) * 2))) for v in WHITE)
            ww = c.text(x, y, w, "sans", size, col, wt, "l", fade)
            if t >= a0 and w.lower().strip(".,?!:;\"'") in S["keywords"]:
                c.line([(x, y + 30), (x + c.tw(w.rstrip(".,?!:;"), "sans", size, wt) * ease((t - a0) / 0.25), y + 30)], WHITE, 3, fade)
            x += ww + c.tw(" ", "sans", size, wt)


# ---------------------------------------------------------------- chrome: header, rail, panel, small parts
def header(c, t):
    left, right = (s.upper() for s in S["spec"]["header"])
    c.text(40, 150, left[:28], "mono", c.fit(left[:28], "mono", 25, "Semibold", 560, 5), WHITE, "Semibold", "l", track=5)
    c.text(W - 40, 150, right[:32], "mono", 17, G1, "Regular", "r", track=3.2)
    c.line([(0, 190), (W, 190)], G3, 1.2)
    for k in range(13): c.line([(20 + k * 87, 184), (20 + k * 87, 196)], G2, 1.2)
    px = W * t / S["dur"]
    c.line([(0, 190), (px, 190)], WHITE, 2); c.line([(px, 181), (px, 199)], WHITE, 2)


def check(c, x, y, a=1.0, r=12, col=WHITE):
    c.circle(x, y, r, fill=col, a=a)
    c.line([(x - r * .42, y), (x - r * .12, y + r * .36), (x + r * .46, y - r * .38)], BLACK, 2.2, a)


def cross(c, x, y, a=1.0, r=12, col=RED):
    c.circle(x, y, r, outline=col, w=1.6, a=a)
    k = r * .38
    c.line([(x - k, y - k), (x + k, y + k)], col, 2, a); c.line([(x - k, y + k), (x + k, y - k)], col, 2, a)


def mark(c, x, y, ok, a, r=11):
    if ok is True: check(c, x, y, a, r)
    elif ok is False: cross(c, x, y, a, r)
    else: c.circle(x, y, 3, fill=G1, a=a)


def mono_tag(c, x, y, s, col=WHITE, a=1.0, filled=False, size=17, anchor="c"):
    tw = c.tw(s, "mono", size, "Semibold" if filled else "Regular", 1.5) + 22
    x0 = x - tw / 2 if anchor == "c" else (x - tw if anchor == "r" else x)
    if filled:
        c.rect([x0, y - 15, x0 + tw, y + 15], 5, fill=col, a=a)
        c.text(x0 + 11, y, s, "mono", size, BLACK, "Semibold", "l", a, track=1.5)
    else:
        c.rect([x0, y - 15, x0 + tw, y + 15], 5, outline=col, w=1.3, a=a)
        c.text(x0 + 11, y, s, "mono", size, col, "Regular", "l", a, track=1.5)


def rail(c, t, active, a, lt):
    chapters = S["spec"].get("chapters", [])
    if a <= 0 or not chapters: return
    cam, n = S["rail_cam"], len(chapters)
    xs = [i - (n - 1) / 2 for i in range(n)]
    x0, x1 = xs[0] - 0.9, xs[-1] + 0.9
    c.line([cam.pt(x0, 0, 0.42), cam.pt(x1, 0, 0.42)], G1, 2, a)
    k = x0
    while k < x1 - 0.1:
        c.line([cam.pt(k, 0, 0.44), cam.pt(k + 0.12, 0, 0.72)], G4, 1, a); k += 0.17
    c.line([cam.pt(x0, 0, 0.72), cam.pt(x1, 0, 0.72)], G4, 1, a)
    for i, x in enumerate(xs):
        done, cur = i < active, i == active
        wire_box(c, cam, x, 0.31, 0, 0.62, 0.62, 0.62, col=WHITE if done or cur else G2, w=1.4 if cur else 1.1, a=a,
                 fill=0.92 * ease(lt * 2) if cur else 0.0)
        if done or cur:
            wire_box(c, cam, x, 0.12, 0, 0.22, 0.22, 0.22, col=G2 if done else G4, a=a, fill=0.5 if done else 0.9,
                     fillcol=(150, 150, 150) if done else (40, 40, 40))
        lx, ly = cam.pt(x, -0.02, 0.9)
        lab = chapters[i]["label"].upper()
        c.text(lx, ly + 16, lab, "mono", c.fit(lab, "mono", 12.5, "Regular", 86, 0.6), WHITE if cur else (G1 if done else G2),
               "Semibold" if cur else "Regular", "c", a, track=0.6)
        dx, dy = cam.pt(x, 1.0, 0)
        if done: check(c, dx, dy, a, 12)
        elif cur: c.circle(dx, dy, 12 + 1.5 * math.sin(t * 4), outline=WHITE, w=1.6, a=a)
        else: c.circle(dx, dy, 2.2, fill=G2, a=a)
    groups, g0 = [], 0
    for i in range(1, n + 1):
        if i == n or chapters[i]["group"] != chapters[g0]["group"]:
            groups.append((chapters[g0]["group"].upper(), g0, i - 1)); g0 = i
    for name, i0, i1 in groups:
        on = i0 <= active <= i1
        b0, b1 = cam.pt(xs[i0] - 0.42, 1.45, 0), cam.pt(xs[i1] + 0.42, 1.45, 0)
        mx, my = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        tw = c.tw(name, "mono", 15, "Semibold", 2) + 22
        col = WHITE if on or active > i1 else G2
        if b1[0] - b0[0] > tw + 30:
            c.line([(b0[0], b0[1] + 10), b0, (mx - tw / 2 - 6, my)], col, 1.2, a)
            c.line([(mx + tw / 2 + 6, my), b1, (b1[0], b1[1] + 10)], col, 1.2, a)
        if on:
            c.rect([mx - tw / 2, my - 14, mx + tw / 2, my + 14], 5, fill=WHITE, a=a)
            c.text(mx, my, name, "mono", 15, BLACK, "Semibold", "c", a, track=2)
        else:
            c.rect([mx - tw / 2, my - 14, mx + tw / 2, my + 14], 5, outline=col, w=1.2, a=a)
            c.text(mx, my, name, "mono", 15, col, "Regular", "c", a, track=2)
    ax, ay = cam.pt(xs[active], -0.02, 0.9)
    for k in range(12): c.circle(ax, ay + 42 + k * 9, 1.2, fill=G1, a=a * (1 - k / 14))


PANEL = (40, 830, W - 40, 1440)


def panel(c, tag, right, a):
    x0, y0, x1, y1 = PANEL
    for (x, y, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        c.line([(x, y + sy * 32), (x, y), (x + sx * 32, y)], WHITE, 2, a)
    if tag:
        tag = tag.upper(); tw = c.tw(tag, "mono", 21, "Semibold", 2.5) + 30
        c.rect([x0 + 30, y0 + 22, x0 + 30 + tw, y0 + 62], 7, fill=WHITE, a=a)
        c.text(x0 + 45, y0 + 42, tag, "mono", 21, BLACK, "Semibold", "l", a, track=2.5)
    if right:
        c.text(x1 - 30, y0 + 42, right.lower(), "mono", 19, G1, "Regular", "r", a, track=1.5)


def laptop(c, cam, x, y, z, s=1.0, a=1.0, col=WHITE):
    P = cam.p(box_verts(x, y + 0.03 * s, z, 1.6 * s, 0.06 * s, 1.0 * s))
    for i, j in EDGES: c.line([tuple(P[i]), tuple(P[j])], col, 1.4, a)
    bz = z - 0.5 * s
    scr = [cam.pt(x - 0.78 * s, y + 0.06 * s, bz), cam.pt(x + 0.78 * s, y + 0.06 * s, bz),
           cam.pt(x + 0.78 * s, y + 1.0 * s, bz - 0.25 * s), cam.pt(x - 0.78 * s, y + 1.0 * s, bz - 0.25 * s)]
    c.poly(scr, fill=(10, 10, 12), outline=col, a=a, w=1.6)
    for k in range(3):
        u = 0.3 + k * 0.17
        c.line([(lerp(scr[0][0], scr[3][0], u) + 30 * s, lerp(scr[0][1], scr[3][1], u)),
                (lerp(scr[1][0], scr[2][0], u) - (90 + 40 * k) * s, lerp(scr[1][1], scr[2][1], u))], G2, 1.2, a)


def footnote(c, s, a):
    if s: c.text(80, 1400, s, "mono", c.fit(s, "mono", 16, "Regular", 900, 0.5), G2, "Regular", "l", a, track=0.5)


# ================================================================ element library
# fn(c, sc, t, lt, sd, amp): sc = scene dict, t absolute time, lt time since scene start,
# sd scene length, amp smoothed voice loudness 0..1.

def el_particle_word(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a0, b0 = scene_window(sc["id"])
    prev = prev_scene(sc["id"])
    src = shape(particle_word(prev)) if prev and prev["visual"]["type"] in ("particle_word", "comment") else SHAPES["cloud"]
    P = morph(t, a0 - (0.1 if src is not SHAPES["cloud"] else -0.2), 2.0, src, shape(particle_word(sc)))
    draw_points(c, P, W / 2, 900, yaw=0.32 * math.sin(t * 0.55), pitch=0.06 * math.sin(t * 0.4))
    think0 = S["lines_by_scene"][sc["id"]][-1]["end"]
    if v.get("countdown") and t >= think0:
        n = v["countdown"]; k = clamp((t - think0) / max(0.5, b0 - think0))
        c.circle(W / 2, 900, 440, outline=G4, w=1.2)
        c.arc(W / 2, 900, 440, -90, -90 + 360 * (1 - k), WHITE, 1.6)
        c.text(W / 2, 1400, f"00:0{max(1, n - int(k * n))}", "mono", 44, WHITE, "Semibold", "c", 1, track=6)
        c.text(W / 2, 1450, "PAUSE  ·  THINK", "mono", 17, G1, "Regular", "c", 1, track=4)
    else:
        c.circle(W / 2, 900, 470, outline=G3, w=1.2, a=ease(lt / 1.2))
        if v.get("subtitle"):
            s = v["subtitle"].upper()
            c.text(W / 2, 1150, s, "mono", c.fit(s, "mono", 20, "Regular", 820, 4), G1, "Regular", "c", ease((lt - 1.2) / 0.8), track=4)


def el_orb(c, sc, t, lt, sd, amp):
    v = sc["visual"]
    orb(c, W / 2, 900, 290, t, amp, a=ease(lt / 1.0))
    if v.get("word"):
        c.text(W / 2, 1260, v["word"], "mono", c.fit(v["word"], "mono", 21, "Semibold", 900, 4), WHITE, "Semibold", "c", ease((lt - 0.5) * 1.5), track=4)
    if v.get("subtitle"):
        c.text(W / 2, 1305, v["subtitle"], "mono", 18, G1, "Regular", "c", ease((lt - 1.2) * 1.5), track=2)


def el_two_party(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    lines = S["lines_by_scene"][sc["id"]]
    has_r = any(x["spk"] == "R" for x in lines)
    cur = next((x for x in lines if x["start"] <= t < x["end"]), None)
    ai_talk = amp if cur and (cur["spk"] == "R" or (not has_r and cur["spk"] == "N")) else 0.0
    you_talk = amp if cur and cur["spk"] == "C" else 0.0
    a0, _ = scene_window(sc["id"])
    c_line = next((x for x in lines if x["spk"] == "C"), None)
    ct = a0 + v["conflict_at"] * sd if v.get("conflict_at") is not None else (c_line["start"] if c_line else None)
    collide = ct is not None and ct <= t < ct + 1.6
    orb(c, 255, 1075, 105, t, ai_talk + (0.35 * abs(math.sin(t * 13)) if collide else 0), a=a, n=1500, red=collide)
    c.text(255, 1240, (v.get("left") or "AI").upper(), "mono", 16, WHITE, "Semibold", "c", a, track=2.5)
    laptop(c, Cam(-0.5, 0.42, 9, 900, 830, 1150), 0, 0, 0, 1.25, a=a)
    c.text(830, 1240, (v.get("right") or "YOU").upper(), "mono", 16, WHITE, "Semibold", "c", a, track=2.5)
    x0, x1, y = 395, 690, 1075
    c.dline((x0, y), (x1, y), G2, 1.3, a, dash=6, gap=6)
    for q in range(4):
        if ai_talk > 0.05 or collide:
            u = (t * 0.7 + q / 4) % 1
            c.rect([lerp(x0, x1, u) - 5, y - 19, lerp(x0, x1, u) + 5, y - 9], 1, fill=WHITE, a=a)
        if you_talk > 0.05:
            u = 1 - (t * 0.8 + q / 4) % 1
            c.rect([lerp(x0, x1, u) - 5, y + 9, lerp(x0, x1, u) + 5, y + 19], 1, outline=WHITE, w=1.4, a=a)
    if collide:
        k = (t - ct) / 1.6
        cross(c, (x0 + x1) / 2, y, a=ease(k * 5), r=20)
        mono_tag(c, (x0 + x1) / 2, y - 60, (v.get("subtitle") or "OVERLAP").upper()[:20], RED, a=ease(k * 5))
    items = v.get("items") or []
    for i, it in enumerate(items[:3]):
        aa = reveal(lt, sd, i, len(items), it, span=0.35, start=0.55) * a
        yy = 1290 + i * 46
        mark(c, 120, yy, it.get("ok"), aa, 12)
        c.text(150, yy, it["name"], "mono", 22, WHITE if it.get("ok") else G1, "Semibold" if it.get("ok") else "Regular", "l", aa, track=1)


def el_pipeline(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    items = (v.get("items") or [])[:5] or [{"name": "A"}, {"name": "B"}]
    n = len(items)
    gap = 2.2 if n >= 5 else 2.6
    xs = [(i - (n - 1) / 2) * gap for i in range(n)]
    sizes = [(1.0, 1.0, 1.0), (0.8, 1.4, 0.8), (1.3, 0.35, 0.5), (1.1, 0.8, 0.8), (0.7, 0.9, 0.7)][:n]
    cam = Cam(-0.13, 0.36, 12.5, 1000 if n >= 5 else 1100, W / 2 + 10, 1130)
    c.line([cam.pt(xs[0] - 1.2, 0, 0.75), cam.pt(xs[-1] + 1.2, 0, 0.75)], G3, 1.2, a)
    state = []
    for i, it in enumerate(items):
        k = ease((lt - (it.get("at") if it.get("at") is not None else 0.4) * sd) / 0.4)
        hot = it.get("color") == "red" and k > 0
        stopped = it.get("ok") is False and k > 0
        state.append((hot, stopped))
        sx, sy, sz = sizes[i]
        wire_box(c, cam, xs[i], sy / 2, 0, sx, sy, sz, col=RED if hot else (G1 if stopped else WHITE), w=1.5, a=a, fill=0 if stopped else 0.12)
        lx, ly = cam.pt(xs[i], -0.05, 1.15)
        nm = it["name"].upper()
        c.text(lx, ly + 10, nm, "mono", c.fit(nm, "mono", 17, "Semibold", 170, 2), RED if hot else WHITE, "Semibold", "c", a, track=2)
        c.text(lx, ly + 36, "stopped" if stopped else it.get("sub", ""), "mono", 15, RED if hot else G2, "Regular", "c", a, track=1)
        tag = (it.get("lines") or [""])[0]
        if (hot or stopped) and tag:
            tx, ty = cam.pt(xs[i], sy + (0.55 if i % 2 == 0 else 1.25), 0)
            mono_tag(c, tx, ty - 6, tag[:22], RED if hot else WHITE, a=a * k, filled=stopped, size=15)
    for i in range(n - 1):
        x0 = xs[i] + sizes[i][0] / 2; x1 = xs[i + 1] - sizes[i + 1][0] / 2
        c.dline(cam.pt(x0, 0.25, 0), cam.pt(x1, 0.25, 0), G2, 1.3, a, dash=5, gap=5, phase=t * 1.5)
        if state[i][1] or state[i + 1][1]: continue
        red = state[i][0] or state[i + 1][0]
        for q in range(2):
            px = lerp(x0, x1, (t * 0.55 + q / 2 + i * 0.13) % 1)
            wire_box(c, cam, px, 0.25, 0, 0.13, 0.13, 0.13, col=RED if red else WHITE, w=1, a=a, fill=0.9, fillcol=RED if red else WHITE)
    footnote(c, v.get("subtitle"), a)


def el_checklist(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    items = (v.get("items") or [])[:6]
    step = min(86, 440 / max(1, len(items)))
    y0 = 1140 - step * (len(items) - 1) / 2
    for i, it in enumerate(items):
        aa = reveal(lt, sd, i, len(items), it) * a
        y = y0 + i * step + (1 - aa) * 14
        mark(c, 105, y, it.get("ok"), aa, 13)
        c.text(140, y - (12 if it.get("sub") else 0), it["name"], "sans", c.fit(it["name"], "sans", 34, "Semibold", 820),
               RED if it.get("color") == "red" else WHITE, "Semibold", "l", aa)
        if it.get("sub"): c.text(140, y + 24, it["sub"], "mono", 17, G1, "Regular", "l", aa, track=0.5)
    footnote(c, v.get("subtitle"), a)


def el_graph(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    x0, x1, yb, ytop = 90, 990, 1240, 940
    thr_v = v.get("threshold") or 0.8
    thr = yb - (yb - ytop) * thr_v
    xs = np.linspace(x0, x1, 260); u = (xs - x0) / (x1 - x0)
    tt = u * 7 - t * 0.9
    lvl = 0.12 + 0.22 * np.abs(np.sin(tt * 2.7)) * np.abs(np.sin(tt * 1.1 + 1))
    w = np.clip(np.minimum((tt % 7) - 4.2, 5.9 - (tt % 7)) * 6, 0, 1)
    lvl = lvl * (1 - w) + w * (thr_v + 0.1 + 0.05 * np.sin(tt * 11))
    ys = yb - (yb - ytop) * np.clip(lvl, 0, 1)
    pts = list(zip(xs, ys))
    c.poly(pts + [(x1, yb), (x0, yb)], fill=G1, a=a * 0.07); c.line(pts, G1, 1.6, a)
    above = ys < thr; i = 0
    while i < len(xs):
        if above[i]:
            j = i
            while j < len(xs) and above[j]: j += 1
            seg = list(zip(xs[i:j], ys[i:j]))
            if len(seg) > 1: c.poly(seg + [(xs[j - 1], yb), (xs[i], yb)], fill=WHITE, a=a * 0.16); c.line(seg, WHITE, 2.6, a)
            i = j
        else: i += 1
    c.dline((x0, thr), (x1, thr), WHITE, 1.3, a, dash=8, gap=6)
    c.text(x1, thr - 18, (v.get("word") or f"threshold {thr_v:g}").lower(), "mono", 17, WHITE, "Regular", "r", a, track=1)
    c.line([(x0, yb), (x1, yb)], G3, 1.2, a)
    if v.get("subtitle"): c.text(x0, yb + 26, v["subtitle"], "mono", 15, G2, "Regular", "l", a, track=0.5)
    items = (v.get("items") or [])[:3]
    for i, it in enumerate(items):
        aa = reveal(lt, sd, i, len(items), it) * a
        c.text(90, 1320 + i * 34, it["name"], "mono", 18, G1, "Regular", "l", aa, track=0.5)
        c.text(470, 1320 + i * 34, it.get("sub", ""), "mono", 18, WHITE, "Semibold", "l", aa, track=0.5)


def el_timeline(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    x0, x1, y = 100, 980, 1180
    c.line([(x0, y), (x1, y)], G2, 1.3, a)
    for k in range(12): c.line([(x0 + (x1 - x0) * k / 11, y - 6), (x0 + (x1 - x0) * k / 11, y + 6)], G3, 1.2, a)
    c.text(x1, y + 28, "time", "mono", 15, G2, "Regular", "r", a, track=1)
    items = (v.get("items") or [])[:4]
    xs = []
    for i, it in enumerate(items):
        aa = reveal(lt, sd, i, len(items), None, span=0.25, start=0.04) * a
        x = lerp(x0, x1, it["at"] if it.get("at") is not None else (i + 1) / (len(items) + 1)); xs.append(x)
        col = COLORS.get(it.get("color"), WHITE)
        c.dline((x, 960), (x, y), col, 1.3, aa, dash=4, gap=4)
        c.circle(x, y, 7, fill=col, a=aa)
        c.text(x, 940, it["name"], "mono", c.fit(it["name"], "mono", 17, "Semibold", 300, 1), col, "Semibold", "c", aa, track=1)
    m = v.get("marker")
    if m and xs:
        fi = max(0, min(len(xs) - 1, m.get("from_index", 0)))
        ti = m.get("to_index"); ti = fi if ti is None else max(0, min(len(xs) - 1, ti))
        mk = ease_io((lt / sd - 0.45) * 3) if ti != fi else 0
        mx = lerp(xs[fi], xs[ti], mk)
        col = COLORS.get(m.get("color"), RED) if (ti == fi or mk < 0.5) else WHITE
        aa = ease((lt / sd - 0.25) * 5) * a
        mono_tag(c, mx, 1060, m["text"], col, a=aa, size=17, filled=ti != fi and mk >= 1)
        if m.get("note"): c.text(mx, 1100, m["note"], "mono", 15, col, "Regular", "c", aa if ti == fi else ease((mk - 0.9) * 10) * a, track=1)
    if v.get("subtitle"):
        red = bool(m and m.get("color") == "red" and m.get("to_index") is None)
        c.text(540, 1330, v["subtitle"], "mono", c.fit(v["subtitle"], "mono", 20, "Regular", 900, 0.3), RED if red else G1, "Regular", "c",
               ease((lt / sd - 0.6) * 5) * a, track=0.3)


def el_cards(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    items = (v.get("items") or [])[:4]
    y = 935
    for i, it in enumerate(items):
        aa = reveal(lt, sd, i, len(items), it) * a
        if aa <= 0: break
        lines = (it.get("lines") or [it.get("sub", "")])[:2]
        h = 46 + 34 * len(lines); yy = y + (1 - aa) * 30
        c.rect([100, yy - 10, 1000, yy + h - 10], 10, outline=G3, w=1.2, a=aa)
        c.rect([90, yy, 990, yy + h], 10, fill=(8, 8, 9), outline=WHITE, w=1.5, a=aa)
        c.text(115, yy + 28, it["name"], "mono", 17, G1, "Semibold", "l", aa, track=2)
        red = it.get("color") == "red"
        if it.get("sub") and it.get("lines"): mono_tag(c, 965, yy + 28, it["sub"][:18], RED if red else WHITE, a=aa, size=14, anchor="r", filled=not red)
        for j, ln in enumerate(lines):
            c.text(115, yy + 64 + j * 34, ln, "mono", c.fit(ln, "mono", 20, "Regular", 840, 0.3), WHITE, "Regular", "l", aa, track=0.3)
        if red:
            ex = min(975, 115 + c.tw(lines[-1], "mono", 20, "Regular", 0.3) + 10)
            c.dline((ex, yy + 50), (ex, yy + h - 6), RED, 2, aa, dash=5, gap=4)
        y += h + 26


def el_code(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    wire_box(c, Cam(-0.5, 0.42, 9, 700, 900, 1000), 0, 0, 0, 0.9, 0.9, 0.9, col=G2, w=1.2, a=a * 0.8)
    code = (v.get("code") or [])[:6]; hl = v.get("highlight")
    size = min(c.fit(max(code, key=len) if code else "x", "mono", 22, "Regular", 900), 22)
    for i, ln in enumerate(code):
        aa = reveal(lt, sd, i, len(code), None, span=0.5) * a
        on = hl == i and lt > sd * 0.55
        if on: c.rect([70, 1000 + i * 44, 1010, 1040 + i * 44], 6, fill=WHITE, a=aa * 0.1)
        c.text(80, 1020 + i * 44, ln, "mono", size, WHITE if on or hl is None else G1, "Semibold" if on else "Regular", "l", aa)
    if v.get("subtitle"): c.text(1000, 1395, v["subtitle"], "mono", 16, WHITE, "Regular", "r", ease((lt / sd - 0.7) * 5) * a, track=1)


def el_compare(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    items = (v.get("items") or [])[:3]; n = len(items)
    cam = Cam(-0.25, 0.35, 10, 1000, W / 2, 1150)
    for i, it in enumerate(items):
        x = (i - (n - 1) / 2) * 3.0
        cur = bool(it.get("ok"))
        aa = a if cur else reveal(lt, sd, i, n, it, span=0.5, start=0.2) * a
        wire_box(c, cam, x, 0.6 + (0 if cur else 0.08 * math.sin(t * 1.5 + x)), 0, 1.2, 1.2, 1.2, col=WHITE if cur else G1, w=1.4,
                 a=aa, fill=0.9 if cur else 0, dashed=not cur)
        lx, ly = cam.pt(x, -0.1, 1.0)
        c.text(lx, ly + 20, it["name"], "mono", c.fit(it["name"], "mono", 17, "Semibold", 280, 1), WHITE if cur else G1, "Semibold", "c", aa, track=1)
        c.text(lx, ly + 46, it.get("sub", ""), "mono", 15, G2, "Regular", "c", aa, track=1)
        if not cur:
            tx, ty = cam.pt(x, 1.75, 0)
            c.text(tx, ty, "?", "sans", 40, G1, "Light", "c", aa)
    c.line([cam.pt(-4.5, 0, 0.8), cam.pt(4.5, 0, 0.8)], G3, 1.2, a)
    footnote(c, v.get("subtitle"), a)


def el_waveform(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    x0, x1, yb = 90, 990, 1150
    xs = np.linspace(x0, x1, 240); u = (xs - x0) / (x1 - x0)
    items = (v.get("items") or [])[:3]
    silent = np.zeros_like(u, bool)
    for it in items:
        if it.get("color") != "white" and it.get("start") is not None and it.get("end") is not None:
            silent |= (u >= it["start"]) & (u <= it["end"])
    env = np.where(silent, 0.03, 0.3 + 0.7 * np.abs(np.sin(u * 40 + t * 2)) * np.abs(np.sin(u * 9)))
    env = np.convolve(env * np.sin(np.pi * u) ** 0.3, np.ones(5) / 5, mode="same")
    top = yb - 150 * env
    c.poly(list(zip(xs, top)) + [(x1, yb), (x0, yb)], fill=WHITE, a=a * 0.1)
    c.line(list(zip(xs, top)), WHITE, 1.8, a); c.line(list(zip(xs, 2 * yb - top)), G2, 1.2, a)
    for i, it in enumerate(items):
        if it.get("start") is None or it.get("end") is None: continue
        aa = reveal(lt, sd, i, len(items), it, span=0.6, start=0.15) * a
        bx0, bx1 = lerp(x0, x1, it["start"]), lerp(x0, x1, it["end"])
        col = COLORS.get(it.get("color"), WHITE)
        c.line([(bx0, 960), (bx0, 950), (bx1, 950), (bx1, 960)], col, 1.5, aa)
        c.text((bx0 + bx1) / 2, 925, it["name"], "mono", c.fit(it["name"], "mono", 18, "Semibold", max(160, bx1 - bx0 + 80), 1), col, "Semibold", "c", aa, track=1)
        if it.get("color") != "white": c.text((bx0 + bx1) / 2, yb, "?", "sans", 70, col, "Light", "c", aa)
    footnote(c, v.get("subtitle"), a)


def el_sources(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a = ease(lt / 0.6)
    panel(c, v.get("tag"), v.get("label"), a)
    cx, cy = W / 2, 1110
    orb(c, cx, cy, 70, t, 0.3, a=a, ring=False, n=900)
    c.text(cx, cy + 115, v.get("word") or "INPUT", "mono", 16, WHITE, "Semibold", "c", a, track=3)
    pos = [(175, 975), (905, 975), (175, 1290), (905, 1290)]
    items = (v.get("items") or [])[:4]
    for i, it in enumerate(items):
        sx, sy = pos[i]; real = bool(it.get("ok"))
        aa = reveal(lt, sd, i, len(items), it, span=0.45) * a
        wire_box(c, Cam(-0.5, 0.4, 8, 700, sx, sy), 0, 0, 0, 0.7, 0.7, 0.7, col=WHITE if real else G1, w=1.3, a=aa, fill=0.85 if real else 0)
        c.text(sx, sy + 62, it["name"], "mono", 17, WHITE if real else G1, "Semibold" if real else "Regular", "c", aa, track=1.5)
        ex = cx + (-80 if sx < cx else 80)
        pts = [((1 - u) ** 2 * sx + 2 * (1 - u) * u * (cx + sx) / 2 + u * u * ex, (1 - u) ** 2 * sy + 2 * (1 - u) * u * cy + u * u * cy)
               for u in np.linspace(0, 1, 40)]
        for j in range(0, 39, 2): c.line([pts[j], pts[j + 1]], G2, 1.2, aa)
        for q in range(3):
            j = int(((t * 0.5 + q / 3 + i * 0.2) % 1) * 39)
            c.circle(pts[j][0], pts[j][1], 3, fill=WHITE if real else G1, a=aa)
        vk = ease((lt / sd - 0.72) * 5)
        if vk > 0 and it.get("ok") is not None:
            vx = sx + (70 if sx < cx else -70)
            if real: check(c, vx, sy - 40, vk * a, 11)
            else: cross(c, vx, sy - 40, vk * a, 11, col=G1)
    footnote(c, v.get("subtitle"), a)


def el_comment(c, sc, t, lt, sd, amp):
    v = sc["visual"]; a0, _ = scene_window(sc["id"])
    prev = prev_scene(sc["id"])
    src = shape(particle_word(prev)) if prev and prev["visual"]["type"] in ("particle_word", "comment") else SHAPES["sphere"]
    draw_points(c, morph(t, a0 - 0.2, 1.5, src, shape(particle_word(sc))), W / 2, 820, yaw=0.25 * math.sin(t * 0.6))
    a = ease((lt - 0.4) * 2)
    c.rect([90, 1080, 990, 1160], 40, outline=G2, w=1.5, a=a)
    typed = (v.get("subtitle") or "my approach would be…")[: int(max(0, lt - 1.2) * 14)]
    caret = "|" if int(t * 2.2) % 2 == 0 else " "
    c.text(130, 1120, (typed or "Add comment…") + (caret if typed else ""), "sans", 30, WHITE if typed else G2, "Regular", "l", a)
    c.text(W / 2, 1220, "EXPLAIN IT IN THE COMMENTS", "mono", 19, G1, "Regular", "c", a, track=4)


ELEMENTS = {"particle_word": el_particle_word, "orb": el_orb, "two_party": el_two_party, "pipeline": el_pipeline,
            "checklist": el_checklist, "graph": el_graph, "timeline": el_timeline, "cards": el_cards, "code": el_code,
            "compare": el_compare, "waveform": el_waveform, "sources": el_sources, "comment": el_comment}


# ---------------------------------------------------------------- frame + render
def rail_alpha(t):
    for a0, b0 in S["rail_blocks"]:
        if a0 <= t < b0: return min(ease((t - a0) / 0.6), ease((b0 - t) / 0.45))
    return 0.0


def frame(fi):
    t = fi / FPS
    amp = float(S["env"][min(fi, S["nf"] - 1)])
    c = Cv()
    name, lt, sd = scene_at(t)
    sc = S["scene_by_id"][name]
    ra = rail_alpha(t)
    if ra > 0 and sc.get("chapter") is not None:
        ch = sc["chapter"]
        ch_start = min(a for n, a, b in S["wins"] if S["scene_by_id"][n].get("chapter") == ch)
        rail(c, t, ch, ra, t - ch_start)
    ELEMENTS[sc["visual"]["type"]](c, sc, t, lt, sd, amp)
    header(c, t)
    captions(c, t)
    return c.finish(fade=max(0.0, min(1.0, t / 0.4, (S["dur"] - t) / 0.8)))


def _chunk(args):
    workdir, k, a, b, out = args
    if S.get("_wd") != workdir:
        load(workdir); S["_wd"] = workdir
    pr = subprocess.Popen(ffmpeg("-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                                 "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", out), stdin=subprocess.PIPE)
    for fi in range(a, b): pr.stdin.write(frame(fi).tobytes())
    pr.stdin.close()
    if pr.wait() != 0: raise RuntimeError(f"ffmpeg failed on chunk {k}")
    return k


def render(workdir, progress=lambda f: None, procs=None):
    load(workdir)
    nf = S["nf"]
    procs = procs or max(1, (os.cpu_count() or 2) - 1)
    cdir = os.path.join(workdir, "chunks"); os.makedirs(cdir, exist_ok=True)
    edges = np.linspace(0, nf, procs * 4 + 1).astype(int)
    jobs = [(workdir, i, int(edges[i]), int(edges[i + 1]), os.path.join(cdir, f"c{i:03d}.mp4")) for i in range(len(edges) - 1)]
    done = 0
    if procs == 1:                   # small machines: render in-process, no pool memory
        for j in jobs:
            _chunk(j); done += 1; progress(done / len(jobs))
    else:
        with Pool(procs) as pool:
            for _ in pool.imap_unordered(_chunk, jobs):
                done += 1; progress(done / len(jobs))
    with open(os.path.join(cdir, "list.txt"), "w") as f:
        for j in jobs: f.write(f"file '{j[4]}'\n")
    subprocess.run(ffmpeg("-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(cdir, "list.txt"), "-c", "copy",
                          os.path.join(workdir, "video_silent.mp4")), check=True)
    return S["dur"]


def stills(workdir, times, out_dir):
    load(workdir)
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for ts in times:
        p = os.path.join(out_dir, f"s{ts:06.1f}.jpg")
        Image.fromarray(frame(int(ts * FPS))).save(p, quality=88); paths.append(p)
    return paths


def contact_sheet(paths, out, cols=4):
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 360, rows * 640), (80, 80, 80))
    for i, p in enumerate(paths):
        sheet.paste(Image.open(p).resize((356, 633)), ((i % cols) * 360, (i // cols) * 640))
    sheet.save(out, quality=85)
    return out
