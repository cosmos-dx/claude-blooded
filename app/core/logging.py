from __future__ import annotations

import logging
import sys


def setup(level: str = "INFO") -> None:
    logging.basicConfig(stream=sys.stdout, level=level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
