"""Text-to-speech contract; implementations register by name (tts.provider in config)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.registry import Registry


@dataclass
class Voice:
    code: str
    voice_id: str
    language: str
    gender: str
    persona: str
    settings: dict


class TTSProvider(ABC):
    name = "tts"

    def __init__(self, settings: dict):
        self.settings = settings

    @abstractmethod
    def synthesize(self, text: str, voice: Voice, model: str, out_mp3: str) -> int:
        """Write speech to out_mp3; return billed characters."""

    def usd_per_1k(self, model: str) -> float:
        return float((self.settings.get("usd_per_1k_chars") or {}).get(model, 0.0))


TTS: Registry[TTSProvider] = Registry("tts provider")
