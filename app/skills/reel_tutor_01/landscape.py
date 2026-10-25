"""16:9 for the point-cloud style. The vertical stage keeps its own layout and sits on the right of a
1920x1080 canvas in the theme's colours; the left column is typeset once: header label, title, an accent rule
and the numbered chapter list (60-30-10 holds: ground, ink, one accent rule)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.ffmpeg import ffmpeg

SIZE = (1920, 1080)
MARGIN = 120


def _font(family: str, weight: int, size: int):
    root = Path(os.environ.get("REEL_FONT_DIR", "/usr/share/fonts/reel")) / family
    have = sorted(int(p.stem) for p in root.glob("*.ttf") if p.stem.isdigit()) if root.is_dir() else []
    if not have:
        return ImageFont.load_default(size)
    w = min(have, key=lambda x: (abs(x - weight), -x))
    return ImageFont.truetype(str(root / f"{w}.ttf"), size)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    rows, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            rows.append(cur)
            cur = word
    return rows + ([cur] if cur else [])


def panel(spec: dict, theme, out: Path) -> int:
    """Draw the static canvas; returns the x where the stage goes."""
    W, H = SIZE
    ground, ink, accent = tuple(theme.stops[0][1]), tuple(theme.stops[-1][1]), tuple(theme.accent)
    mid = tuple(round(g + (i - g) * 0.35) for g, i in zip(ground, ink))
    stage_w = round(H * 9 / 16)
    x_stage = W - stage_w - 96
    col_w = x_stage - MARGIN - 96
    im = Image.new("RGB", SIZE, ground)
    d = ImageDraw.Draw(im)

    mono = _font(theme.mono, 600, 22)
    d.text((MARGIN, 150), "  ·  ".join(h for h in spec.get("header", []) if h).upper()[:80], font=mono, fill=accent, anchor="lm")

    size, rows = 112, []
    while size >= 56:                                    # the title takes at most four rows
        rows = _wrap(d, spec.get("title", ""), _font(theme.sans, 800, size), col_w)
        if len(rows) <= 4:
            break
        size -= 8
    title_font, y = _font(theme.sans, 800, size), 230
    for r in rows:
        d.text((MARGIN, y), r, font=title_font, fill=ink, anchor="lt")
        y += round(size * 1.08)
    y += 36
    d.rectangle([MARGIN, y, MARGIN + 96, y + 6], fill=accent)
    y += 60

    item = _font(theme.mono, 400, 26)
    for i, ch in enumerate(spec.get("chapters", [])[:8], 1):
        d.text((MARGIN, y), f"{i:02d}", font=mono, fill=accent, anchor="lm")
        d.text((MARGIN + 70, y), f"{ch.get('label', '')}  ·  {ch.get('group', '')}".upper(), font=item, fill=ink, anchor="lm")
        y += 54
    d.rectangle([x_stage - 2, 0, x_stage - 1, H], fill=mid)    # hairline edge of the stage
    im.save(out)
    return x_stage


def compose(workdir: Path, spec: dict, theme) -> Path:
    """workdir/video_silent.mp4 (9:16) -> the same file as 16:9."""
    stage = workdir / "stage_9x16.mp4"
    (workdir / "video_silent.mp4").rename(stage)
    canvas = workdir / "landscape.png"
    x = panel(spec, theme, canvas)
    subprocess.run(ffmpeg("-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(canvas), "-i", str(stage),
                          "-filter_complex", f"[1:v]scale=-2:{SIZE[1]}[s];[0:v][s]overlay={x}:0:shortest=1,format=yuv420p[v]",
                          "-map", "[v]", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                          str(workdir / "video_silent.mp4")), check=True)
    stage.unlink()
    canvas.unlink()
    return workdir / "video_silent.mp4"
