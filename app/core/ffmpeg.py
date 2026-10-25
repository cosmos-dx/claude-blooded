"""ffmpeg invocation. On macOS dev machines Homebrew's ffmpeg can link an x265 dylib that a later
`brew upgrade` removed; fall back to an older x265 still in the Cellar. No-op on the server."""
from __future__ import annotations

import glob
import os
import subprocess

_ok_checked = False


def _runs(env=None) -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True, env=env).returncode == 0
    except FileNotFoundError:
        return False


def ensure() -> None:
    global _ok_checked
    if _ok_checked or _runs():
        _ok_checked = True
        return
    for lib in sorted(glob.glob("/opt/homebrew/Cellar/x265/*/lib"), reverse=True):
        if _runs(dict(os.environ, DYLD_LIBRARY_PATH=lib)):
            os.environ["DYLD_LIBRARY_PATH"] = lib
            _ok_checked = True
            return
    raise RuntimeError("ffmpeg is not installed or does not run")


def ffmpeg(*args: str) -> list[str]:
    ensure()
    return ["ffmpeg", *args]


def probe_duration(path: str) -> float:
    ensure()
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True)
    return float(out.stdout.strip() or 0)
