"""The reel pipeline steps. Order comes from config (workflows.reel)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core import logging as log
from app.core.errors import AppError
from app.core.ffmpeg import ffmpeg, probe_duration
from app.skills import audio, music
from app.tts.base import Voice
from app.workflows.base import STEPS, ReelContext, Step


@STEPS.register("moderate")
class Moderate(Step):
    name, weight = "moderate", 0.3

    def run(self, ctx: ReelContext, progress) -> str:
        if not self.deps.config.get("moderation.enabled", True):
            return "skipped"
        verdict = self.deps.agents["moderator"].check(ctx.request)
        if not verdict["allow"]:
            raise AppError(f"request declined: {verdict['reason']}", code="moderation")
        return "allowed"


@STEPS.register("research")
class Research(Step):
    name, weight = "research", 1.0

    def run(self, ctx: ReelContext, progress) -> str:
        ctx.trends = [t["digest"] for t in self.deps.trends.latest()]
        ctx.research, sources = self.deps.agents["researcher"].research(ctx.request, ctx.tier, ctx.trends)
        n = self.deps.design.save_research(str(ctx.job["id"]), ctx.request, ctx.research, sources)
        web = f" · {len(sources)} sources" if sources else ""
        return f"{ctx.research.get('angle', '')[:180]} ({n} facts{web})"


@STEPS.register("design")
class Design(Step):
    """The Design Director's brief. Never fails the reel: without it, an "auto" theme falls back to the style's default."""
    name, weight = "design", 0.8

    def run(self, ctx: ReelContext, progress) -> str:
        if not self.deps.config.get("design.enabled", True):
            return "skipped"
        svc = self.deps.design
        try:
            ctx.design = self.deps.agents["design_director"].design(
                ctx.request, ctx.research, ctx.skill.code, ctx.format, ctx.tier, ctx.trends,
                svc.system.catalog_text(), svc.system.rules(), svc.finalize)
        except AppError as e:
            log.get("design").warning("job %s: design brief skipped: %s", ctx.job["id"], e)
            return f"skipped ({e.message[:120]}); using the style's default theme"
        svc.save_brief(str(ctx.job["id"]), ctx.request, ctx.format, ctx.design)
        p, t = ctx.design["palette"], ctx.design["type"]
        return (f"{p['name']}: {p['dominant']['hex']} / {p['secondary']['hex']} / {p['accent']['hex']} · "
                f"{t['display']['family']} + {t['text']['family']} + {t['accent']['family']} · {ctx.design['research_mode']} research")


@STEPS.register("plan")
class Plan(Step):
    name, weight = "plan", 1.5

    def run(self, ctx: ReelContext, progress) -> str:
        planner = self.deps.agents["planner"]
        ctx.planner_convo = planner.start(ctx.skill, ctx.tier, int(ctx.request["seconds"]), ctx.look)
        ctx.spec = planner.plan(ctx.planner_convo, ctx.skill, ctx.request, ctx.research, ctx.look)
        (ctx.workdir / "plan.json").write_text(json.dumps(ctx.spec, ensure_ascii=False, indent=1))
        return f"{len(ctx.skill.lines(ctx.spec))} lines planned"


@STEPS.register("voice")
class VoiceStep(Step):
    name, weight = "voice", 2.0

    def _voices(self, ctx: ReelContext) -> dict:
        cfg = self.deps.config
        catalog = cfg.get("tts.voices") or []
        cast = self.deps.agents["voice_director"].cast(ctx.request, catalog, cfg.get("tts.defaults"))
        by_code = {v["code"]: v for v in catalog}
        return {role: Voice(**{k: by_code[code][k] for k in ("code", "voice_id", "language", "gender", "persona", "settings")})
                for role, code in cast.items()}

    def run(self, ctx: ReelContext, progress) -> str:
        cfg = self.deps.config
        voices = self._voices(ctx)
        ctx.voices = {r: v.code for r, v in voices.items()}
        model = cfg.get(f"tiers.{ctx.tier}.tts_model")
        tts = self.deps.tts
        limit = float(ctx.request["seconds"]) + float(cfg.get("render.length_tolerance_seconds", 3))

        def chars(n: int):
            self.deps.cost.record_tts(tts.name, model, n, tts.usd_per_1k(model))

        for round_ in range(int(cfg.get("render.shorten_rounds", 2)) + 1):
            ctx.timeline = audio.synthesize(ctx.workdir, ctx.skill.lines(ctx.spec), voices, tts, model, chars, progress)
            if ctx.timeline["duration"] <= limit:
                break
            if round_ == int(cfg.get("render.shorten_rounds", 2)):
                raise AppError(f"the voiceover runs {ctx.timeline['duration']:.0f}s, over the {limit:.0f}s limit", code="too_long")
            ctx.spec = self.deps.agents["planner"].shorten(ctx.planner_convo, ctx.skill, ctx.spec, ctx.timeline, limit - 1)
        return f"{ctx.timeline['duration']:.1f}s voiced with {', '.join(ctx.voices.values())}"


@STEPS.register("render")
class Render(Step):
    name, weight = "render", 6.0

    def run(self, ctx: ReelContext, progress) -> str:
        ctx.skill.render(ctx.workdir, ctx.spec, ctx.look, progress, int(self.deps.config.get("render.processes", 1)))
        return f"rendered {ctx.format}" + (" with the designed palette" if ctx.look.designed else "")


@STEPS.register("mix")
class Mix(Step):
    name, weight = "mix", 1.0

    def run(self, ctx: ReelContext, progress) -> str:
        cfg = self.deps.config
        wd = ctx.workdir
        music.build(str(wd), ctx.skill.music_spec(ctx.spec))
        mark = (cfg.get(f"tiers.{ctx.tier}.watermark") or "").replace("{brand}", str(cfg.get("app.name", "")))
        size = next((tuple(f["size"]) for f in cfg.get("formats") or [] if f["code"] == ctx.format), (1080, 1920))
        overlay = self._watermark(wd, mark, Path(cfg.get("render.font_dir")), size) if mark else None
        loud = cfg.get("render.loudness") or {}
        for src, dst, lufs in (("mix.wav", "reel.mp4", loud.get("voice")), ("music_bed.wav", "reel-no-voice.mp4", loud.get("bed"))):
            inputs = ["-i", str(wd / "video_silent.mp4"), "-i", str(wd / src)] + (["-i", str(overlay)] if overlay else [])
            video = (["-filter_complex", "[0:v][2:v]overlay=0:0[v]", "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
                     if overlay else ["-map", "0:v", "-c:v", "copy"])
            subprocess.run(ffmpeg("-y", "-loglevel", "error", *inputs, *video, "-map", "1:a", "-af", f"loudnorm={lufs}", "-ar", "48000",
                                  "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(ctx.out / dst)), check=True)
        ctx.duration = probe_duration(str(ctx.out / "reel.mp4"))
        self._docs(ctx)
        return f"{ctx.duration:.1f}s video"

    @staticmethod
    def _watermark(wd: Path, text: str, font_dir: Path, size: tuple[int, int]) -> Path:
        """Transparent PNG the size of the video with the watermark near the bottom (works with any ffmpeg build)."""
        from PIL import Image, ImageDraw, ImageFont
        W, H = size
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        font_path = font_dir / "jetbrains-mono" / "400.ttf"
        font = ImageFont.truetype(str(font_path), 26) if font_path.exists() else ImageFont.load_default()
        w = d.textlength(text, font=font)
        cy = H - max(60, round(H * 0.078))
        d.rounded_rectangle([(W - w) / 2 - 16, cy - 22, (W + w) / 2 + 16, cy + 22], 10, fill=(0, 0, 0, 120))
        d.text((W / 2, cy), text, font=font, fill=(255, 255, 255, 200), anchor="mm")
        out = wd / "watermark.png"
        im.save(out)
        return out

    def _docs(self, ctx: ReelContext) -> None:
        def ts(x):
            ms = int(round(x * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        lines = ctx.timeline["lines"]
        (ctx.out / "captions.srt").write_text("".join(f"{i}\n{ts(l['start'])} --> {ts(l['end'])}\n{l['text']}\n\n" for i, l in enumerate(lines, 1)))
        rows = [f"| {i} | {l['start']:.1f}s | {l['spk']} | {l['emo']} | {l['el']} |" for i, l in enumerate(lines, 1)]
        (ctx.out / "script.md").write_text(f"# {ctx.skill.title(ctx.spec)}\n\nVoices: {ctx.voices}\n\n| # | Start | Voice | Emotion | ElevenLabs line |\n|---|---|---|---|---|\n"
                                           + "\n".join(rows) + "\n\n## Plain script\n\n" + "\n".join(l["text"] for l in lines) + "\n")


@STEPS.register("publish")
class Publish(Step):
    name, weight = "publish", 0.5

    def run(self, ctx: ReelContext, progress) -> str:
        ctx.publish = self.deps.agents["publisher"].pack(ctx.spec, ctx.request, ctx.trends)
        p = ctx.publish
        ig, yt = p.get("instagram", {}), p.get("youtube", {})
        md = [f"# {p.get('title', '')}", "", "## Instagram", ig.get("caption", ""), " ".join(ig.get("hashtags", [])), "",
              "## YouTube", f"**Title:** {yt.get('title', '')}", "", yt.get("description", ""), "", " ".join(yt.get("hashtags", [])),
              f"Tags: {', '.join(yt.get('tags', []))}", "", "## LinkedIn", (p.get("linkedin") or {}).get("post", ""), "",
              f"**Best time to post (IST):** {p.get('posting_time_ist', '')}", f"**Pinned comment:** {p.get('pinned_comment', '')}"]
        (ctx.out / "publish.md").write_text("\n".join(md) + "\n")
        return p.get("title", "")[:120]
