"""Postgres access: a small connection pool whose connections use the configured schema (search_path),
plus a `transaction()` context so services can run several DAO calls atomically."""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import Config

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class Database:
    def __init__(self, config: Config):
        self.schema = config.get("database.schema", "public")
        if not _IDENT.match(self.schema):
            raise RuntimeError("database.schema must be a plain lowercase identifier")
        self.pool = ConnectionPool(
            config.require("database.url"),
            min_size=int(config.get("database.pool_min", 1)),
            max_size=int(config.get("database.pool_max", 4)),
            kwargs={"row_factory": dict_row, "autocommit": True, "client_encoding": "utf8"},
            configure=self._configure,
            open=False,
        )
        self._opened = False

    def _configure(self, conn: psycopg.Connection) -> None:
        conn.execute(f"SET search_path TO {self.schema}, public")

    def open(self) -> None:
        if not self._opened:
            self.pool.open(wait=True, timeout=20)
            self._opened = True

    def close(self) -> None:
        if self._opened:
            self.pool.close()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        self.open()                      # lazy: the web app can start (and serve pages) before the DB is reachable
        with self.pool.connection() as conn:
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """One connection, one transaction; pass the yielded connection to DAO methods (`conn=`)."""
        self.open()
        with self.pool.connection() as conn:
            with conn.transaction():
                yield conn
