"""Render the style previews the site shows (web/assets/previews/<skill>-<theme>-<format>.jpg) with the real
pipeline steps and the offline providers (fake LLM + fake TTS). Writes nothing to the database.

usage: APP_ENV=development LLM_FAKE=true TTS_PROVIDER=fake python -m tools.make_previews [skill ...]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from app.agents import agents as _agents  # noqa: F401  (register)
from app.agents.base import AGENTS
from app.core.config import ROOT
from app.core.container import get_container
from app.core.ffmpeg import ffmpeg, probe_duration
from app.llm.router import ModelRouter
from app.services.design_service import DesignService
from app.workflows.base import STEPS, ReelContext, StepDeps
from app.workflows import steps as _steps  # noqa: F401  (register)

OUT = ROOT / "web" / "assets" / "previews"
STEP_NAMES = ("research", "design", "plan", "voice", "render")
WIDTH = {"9:16": 360, "16:9": 640}


class _NoCost:
    def record_tts(self, *a, **k): pass


class _NoTrends:
    def latest(self): return []


class _PreviewDesign(DesignService):
    def save_brief(self, *a, **k): pass
    def save_research(self, *a, **k): return 0


def main(only: list[str]) -> None:
    c = get_container()
    cfg = c.config
    router = ModelRouter(cfg)
    router.profiles = {k: {**v, "providers": ["fake"]} for k, v in router.profiles.items()}   # never spend on previews
    agents = {n: AGENTS.create(n, router, cfg) for n in AGENTS.names()}
    deps = StepDeps(config=cfg, router=router, agents=agents, tts=c.tts, cost=_NoCost(), trends=_NoTrends(),
                    design=_PreviewDesign(None, c.design.system, None, None))
    OUT.mkdir(parents=True, exist_ok=True)
    for code, themes in (cfg.get("skills.themes") or {}).items():
        if only and code not in only:
            continue
        for theme in themes:
            for fmt in (f["code"] for f in cfg.get("formats")):
                wd = Path(tempfile.mkdtemp(prefix="preview-"))
                req = {"problem": "How does a rate limiter stop two servers letting the same request through?", "details": "",
                       "voice_prompt": "", "language": "en-IN", "skill": code, "theme": theme, "format": fmt, "seconds": 30, "narrator": "female"}
                ctx = ReelContext(job={"id": "preview"}, request=req, tier="standard", workdir=wd, skill=c.skills[code], theme=theme, format=fmt)
                for name in STEP_NAMES:
                    STEPS.create(name, deps).run(ctx, lambda f: None)
                video = wd / "video_silent.mp4"
                t = probe_duration(str(video)) * (0.45 if code == "reel-kinetic-01" else 0.5)   # kinetic: a dominant-colour beat
                still = wd / "still.png"
                subprocess.run(ffmpeg("-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(still)), check=True)
                im = Image.open(still).convert("RGB")
                w = WIDTH[fmt]
                im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
                dest = OUT / f"{code}-{theme}-{fmt.replace(':', 'x')}.jpg"
                im.save(dest, quality=82, optimize=True, progressive=True)
                print(f"{dest.name}  {dest.stat().st_size // 1024} KB")
                shutil.rmtree(wd, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
