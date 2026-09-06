from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable


def _database_url() -> str:
    value = os.getenv("EMAIL_DATABASE_URL", "")
    path = os.getenv("EMAIL_DATABASE_URL_FILE", "")
    if not value and path:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
    return value


DATABASE_URL = _database_url()


def is_postgres() -> bool:
    return DATABASE_URL.startswith(("postgresql://", "postgres://"))


if is_postgres():
    import psycopg
    from psycopg.rows import dict_row
    IntegrityError = psycopg.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


def _sql(value: str) -> str:
    return value.replace("?", "%s")


class Connection:
    def __init__(self, path: str):
        if is_postgres():
            self.raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            self.raw = sqlite3.connect(path, timeout=15)
            self.raw.row_factory = sqlite3.Row
            self.raw.execute("PRAGMA foreign_keys=ON")

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        self.raw.close()

    def execute(self, sql: str, params: Iterable[Any] = ()):
        return self.raw.execute(_sql(sql) if is_postgres() else sql, params)

    def executescript(self, script: str) -> None:
        if not is_postgres():
            self.raw.executescript(script)
            return
        for statement in script.split(";"):
            statement = statement.strip()
            if statement and not statement.upper().startswith("PRAGMA"):
                self.raw.execute(statement)
