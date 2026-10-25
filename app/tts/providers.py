from __future__ import annotations

import subprocess
import time

import httpx

from app.core.errors import ProviderError
from app.core.ffmpeg import ffmpeg
from app.tts.base import TTS, TTSProvider, Voice


@TTS.register("elevenlabs")
class ElevenLabs(TTSProvider):
    name = "elevenlabs"

    def synthesize(self, text: str, voice: Voice, model: str, out_mp3: str) -> int:
        key = self.settings.get("api_key")
        if not key:
            raise ProviderError("ELEVEN_LABS_API_KEY is not set")
        url = f"{self.settings['base_url']}/v1/text-to-speech/{voice.voice_id}?output_format=mp3_44100_192"
        body = {"text": text, "model_id": model, "voice_settings": voice.settings}
        for attempt in range(4):
            r = httpx.post(url, json=body, headers={"xi-api-key": key, "Accept": "audio/mpeg"}, timeout=180)
            if r.status_code == 200:
                with open(out_mp3, "wb") as f:
                    f.write(r.content)
                return len(text)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise ProviderError(f"ElevenLabs HTTP {r.status_code}: {r.text[:160]}")
        raise ProviderError("ElevenLabs retries exhausted")


@TTS.register("fake")
class FakeTTS(TTSProvider):
    """Timing-only audio (shaped noise, ~2.6 words/s) so layouts can be checked without spending credits."""
    name = "fake"

    def synthesize(self, text: str, voice: Voice, model: str, out_mp3: str) -> int:
        dur = max(1.0, len(text.split()) / 2.6)
        subprocess.run(ffmpeg("-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anoisesrc=d={dur:.2f}:c=pink:a=0.15",
                              "-af", "volume='0.5+0.5*sin(2*PI*4*t)':eval=frame", "-ar", "44100", out_mp3), check=True)
        return 0
