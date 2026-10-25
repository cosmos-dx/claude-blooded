"""Voiceover assembly shared by all skills: synthesize each line (cached by content hash), trim silence,
place lines back to back with their gaps -> voice.wav + timeline.json."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np

from app.core.ffmpeg import ffmpeg
from app.tts.base import TTSProvider, Voice

SR, LEAD_IN = 48000, 0.4


def clean_for_tts(text: str) -> str:
    text = text.replace("[pause]", "…").replace("*", "")
    return re.sub(r"\s+", " ", text).strip()


def _decode(mp3: Path, wav: Path) -> np.ndarray:
    subprocess.run(ffmpeg("-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), "-af",
                          "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                          "silenceremove=start_periods=1:start_threshold=-45dB,areverse", str(wav)), check=True)
    with wave.open(str(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def synthesize(workdir: Path, pairs: list[tuple[str, dict]], voices: dict[str, Voice], tts: TTSProvider, model: str,
               on_chars: Callable[[int], None], progress: Callable[[float], None] = lambda f: None, threads: int = 3) -> dict:
    cache = workdir / "lines"
    cache.mkdir(exist_ok=True)
    done = [0]

    def one(pair):
        _, line = pair
        voice = voices[line.get("spk", "N")]
        text = clean_for_tts(line["el"])
        h = hashlib.sha1(json.dumps([voice.voice_id, voice.settings, model, text]).encode()).hexdigest()[:16]
        mp3 = cache / f"{h}.mp3"
        if not mp3.exists():
            on_chars(tts.synthesize(text, voice, model, str(mp3)))
        audio = _decode(mp3, mp3.with_suffix(".wav"))
        done[0] += 1
        progress(done[0] / len(pairs))
        return audio

    with ThreadPoolExecutor(threads) as ex:
        audio = list(ex.map(one, pairs))
    chunks, lines, t = [np.zeros(int(LEAD_IN * SR), np.float32)], [], LEAD_IN
    scene_speakers: dict[str, set] = {}
    for (scene, line) in pairs:
        scene_speakers.setdefault(scene, set()).add(line.get("spk", "N"))
    for (scene, line), a in zip(pairs, audio):
        if line.get("spk") == "R" and "C" in scene_speakers[scene]:      # the interrupted speaker cuts off abruptly
            n = min(len(a), int(0.06 * SR)); a = a.copy(); a[-n:] *= np.linspace(1, 0, n)
        dur = len(a) / SR
        gap = float(line.get("gap", 0.3))
        lines.append(dict(scene=scene, spk=line.get("spk", "N"), text=line["text"], el=line["el"], emo=line.get("emo", ""),
                          pace=line.get("pace", ""), gap=gap, start=round(t, 3), end=round(t + dur, 3)))
        chunks += [a, np.zeros(int(gap * SR), np.float32)]
        t += dur + gap
    voice = np.concatenate(chunks)
    voice = voice / max(1e-6, float(np.abs(voice).max())) * 0.89
    with wave.open(str(workdir / "voice.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((voice * 32767).astype(np.int16).tobytes())
    timeline = dict(duration=round(t, 3), lines=lines)
    (workdir / "timeline.json").write_text(json.dumps(timeline, indent=1))
    return timeline
