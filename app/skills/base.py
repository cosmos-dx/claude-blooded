"""A skill = one visual style: how the planner should write for it, how its spec is validated, which lines
get voiced, and how frames are rendered. Workflows only talk to this interface; skills register by code."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.core.registry import Registry

Progress = Callable[[float], None]
AUTO = "auto"                   # theme value meaning "use the Design Director's palette"


@dataclass
class Look:
    """How one reel should look: a built-in theme (or AUTO), the canvas format and the finalised design brief."""
    theme: str
    format: str = "9:16"
    brief: Optional[dict] = None

    @property
    def designed(self) -> bool:
        """True when the brief's palette and fonts drive the render."""
        return self.theme == AUTO and bool(self.brief)


class Skill(ABC):
    code: str = ""
    contract: str = ""          # marker the offline fake provider uses to answer with this skill's format

    def __init__(self, settings: dict):
        self.settings = settings

    def guide(self, look: Look) -> str:
        """Planner instructions for this style (the skill's guide.md)."""
        return (Path(__file__).parent / self.code.replace("-", "_") / "guide.md").read_text()

    @abstractmethod
    def builtin_theme(self, theme: str) -> str:
        """`theme` when it is one of this skill's built-in themes, else its default (used when AUTO has no brief)."""

    @abstractmethod
    def validate(self, data: dict, look: Look) -> dict:
        """Parse/repair the planner's JSON into this skill's spec (raise ValueError with a readable reason)."""

    @abstractmethod
    def lines(self, spec: dict) -> list[tuple[str, dict]]:
        """(scene_id, line) pairs in speaking order; line has spk, text, el, emo, pace, gap."""

    @abstractmethod
    def apply_line_edits(self, spec: dict, edits: dict[int, dict]) -> dict:
        """Replace text/el of lines by their speaking-order index (used when the voice runs long)."""

    @abstractmethod
    def music_spec(self, spec: dict) -> dict:
        """A scene list in the shape music.build understands (scene ids must match `lines`)."""

    @abstractmethod
    def render(self, workdir: Path, spec: dict, look: Look, progress: Progress, processes: int) -> Path:
        """Render workdir/video_silent.mp4 (in look.format) from spec + workdir/voice.wav + workdir/timeline.json."""

    def spec_schema(self) -> dict:
        """JSON schema of the plan this skill accepts (shown to developers)."""
        return {}

    def title(self, spec: dict) -> str:
        return spec.get("title", "")


SKILLS: Registry[Skill] = Registry("skill")
