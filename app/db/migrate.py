"""Apply migrations/*.sql in order, once each, inside the configured schema.

usage: python -m app.db.migrate
"""
from __future__ import annotations

from pathlib import Path

import psycopg

from app.core import logging as log
from app.core.config import ROOT, get_config
from app.db.pool import _IDENT

MIGRATIONS = ROOT / "migrations"


def run() -> list[str]:
    config = get_config()
    schema = config.get("database.schema", "public")
    if not _IDENT.match(schema):
        raise RuntimeError("database.schema must be a plain lowercase identifier")
    applied = []
    with psycopg.connect(config.require("database.url"), autocommit=True, client_encoding="utf8") as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(f"SET search_path TO {schema}, public")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(Path(MIGRATIONS).glob("*.sql")):
            if path.stem in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
    return applied


if __name__ == "__main__":
    log.setup()
    names = run()
    print("applied:", ", ".join(names) if names else "nothing (up to date)")
