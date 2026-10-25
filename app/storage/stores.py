"""Where job files live (storage.provider in config). Local disk on the single server; the interface
leaves room for S3 when workers scale out."""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.registry import Registry


class Storage(ABC):
    def __init__(self, settings: dict, data_dir: str):
        self.settings = settings
        self.root = Path(data_dir).resolve()

    @abstractmethod
    def workdir(self, job_id: str) -> Path: ...

    @abstractmethod
    def output(self, job_id: str, name: str) -> Path | None: ...

    @abstractmethod
    def delete(self, job_id: str) -> None: ...


STORES: Registry[Storage] = Registry("storage")


@STORES.register("local")
class LocalStorage(Storage):
    def workdir(self, job_id: str) -> Path:
        p = self.root / "jobs" / str(job_id)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def output(self, job_id: str, name: str) -> Path | None:
        if name not in (self.settings.get("files") or []):
            return None
        p = self.root / "jobs" / str(job_id) / "out" / name
        return p if p.exists() else None

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self.root / "jobs" / str(job_id), ignore_errors=True)
