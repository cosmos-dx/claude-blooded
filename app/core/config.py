"""Configuration: config/app.yaml (+ config/app.<APP_ENV>.yaml overlay) with ${VAR} / ${VAR:-default}
placeholders resolved from the environment. Business code reads values through `Config`, never os.environ."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("APP_CONFIG_DIR", ROOT / "config"))
_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader for local runs (the server uses systemd EnvironmentFile)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _resolve(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v) for v in value]
    if not isinstance(value, str) or "${" not in value:
        return value
    whole = _PLACEHOLDER.fullmatch(value.strip())
    # shell semantics: ${VAR:-default} uses the default when VAR is unset *or empty* (env files keep blank KEY= lines)
    out = _PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), value)
    if whole:  # a value that is exactly one placeholder may become a number or boolean
        if _NUMBER.match(out):
            return float(out) if "." in out else int(out)
        if out.lower() in ("true", "false"):
            return out.lower() == "true"
    return out


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Config:
    """Dotted-path access over the merged, resolved configuration tree."""

    def __init__(self, tree: dict):
        self.tree = tree

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.tree
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, path: str) -> Any:
        value = self.get(path)
        if value in (None, ""):
            raise RuntimeError(f"missing configuration: {path} (set the matching environment variable)")
        return value

    @property
    def env(self) -> str:
        return str(self.get("app.env", "production"))

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache(maxsize=1)
def get_config() -> Config:
    _load_dotenv(ROOT / ".env")
    raw = yaml.safe_load((CONFIG_DIR / "app.yaml").read_text())
    env = os.environ.get("APP_ENV", "production")
    overlay = CONFIG_DIR / f"app.{env}.yaml"
    if overlay.exists():
        raw = _merge(raw, yaml.safe_load(overlay.read_text()) or {})
    return Config(_resolve(raw))
