"""Workflow engine: a workflow is an ordered list of step names from config (workflows.<name>).
Each step is a registered class; the engine runs them in order, records what each one spent and keeps
the job's stage/progress current."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.registry import Registry
from app.skills.base import Skill


@dataclass
class ReelContext:
    job: dict
    request: dict
    tier: str
    workdir: Path
    skill: Skill
    theme: str
    research: dict = field(default_factory=dict)
    spec: dict = field(default_factory=dict)
    timeline: dict = field(default_factory=dict)
    voices: dict = field(default_factory=dict)
    publish: dict = field(default_factory=dict)
    trends: list = field(default_factory=list)
    planner_convo: Any = None
    duration: float = 0.0

    @property
    def out(self) -> Path:
        p = self.workdir / "out"
        p.mkdir(exist_ok=True)
        return p


class Step:
    name = ""
    weight = 1.0                 # share of the progress bar

    def __init__(self, deps: "StepDeps"):
        self.deps = deps

    def run(self, ctx: ReelContext, progress: Callable[[float], None]) -> str:
        """Do the work; return a one-line note for the job's event log."""
        raise NotImplementedError


STEPS: Registry[Step] = Registry("workflow step")


@dataclass
class StepDeps:
    config: Any
    router: Any
    agents: dict
    tts: Any
    cost: Any
    trends: Any


class Workflow:
    def __init__(self, step_names: list[str], deps: StepDeps, on_stage: Callable[[str, float], None],
                 on_event: Callable[[str, str, Any], None]):
        self.steps = [STEPS.create(n, deps) for n in step_names]
        self.deps, self.on_stage, self.on_event = deps, on_stage, on_event
        total = sum(s.weight for s in self.steps)
        self.spans, acc = [], 0.0
        for s in self.steps:
            self.spans.append((acc / total, (acc + s.weight) / total))
            acc += s.weight

    def run(self, ctx: ReelContext) -> None:
        for step, (lo, hi) in zip(self.steps, self.spans):
            last = [0.0]

            def progress(f: float, step=step, lo=lo, hi=hi):
                now = time.time()
                if now - last[0] > 2 or f >= 1:          # throttle DB writes
                    last[0] = now
                    self.on_stage(step.name, lo + (hi - lo) * max(0.0, min(1.0, f)))
            self.on_stage(step.name, lo)
            with self.deps.cost.scope(str(ctx.job["id"])) as tally:
                note = step.run(ctx, progress)
            self.on_event(step.name, note or "", tally)
