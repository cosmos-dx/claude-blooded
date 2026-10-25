"""DAO base: every query goes through here. Pass `conn=` to join a service-level transaction."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg

from app.db.pool import Database


class BaseDAO:
    def __init__(self, db: Database):
        self.db = db

    @contextmanager
    def _conn(self, conn: Optional[psycopg.Connection]) -> Iterator[psycopg.Connection]:
        if conn is not None:
            yield conn
        else:
            with self.db.connection() as c:
                yield c

    def one(self, sql: str, params: tuple | dict = (), conn=None) -> Optional[dict]:
        with self._conn(conn) as c:
            return c.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | dict = (), conn=None) -> list[dict]:
        with self._conn(conn) as c:
            return c.execute(sql, params).fetchall()

    def run(self, sql: str, params: tuple | dict = (), conn=None) -> int:
        with self._conn(conn) as c:
            return c.execute(sql, params).rowcount

    def scalar(self, sql: str, params: tuple | dict = (), conn=None) -> Any:
        row = self.one(sql, params, conn)
        return next(iter(row.values())) if row else None
