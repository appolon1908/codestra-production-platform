from __future__ import annotations

import hashlib
import json
import os
import sqlite3

import psycopg

from .database import DATABASE_URL
from .migrate import TABLES


def digest(rows: list[tuple]) -> str:
    canonical = sorted(json.dumps(list(row), default=str, separators=(",", ":")) for row in rows)
    return hashlib.sha256("\n".join(canonical).encode()).hexdigest()


def main() -> None:
    source = sqlite3.connect(f"file:{os.environ['SQLITE_SOURCE']}?mode=ro", uri=True)
    missing = 0
    with psycopg.connect(DATABASE_URL) as target:
        for table in TABLES:
            source_rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
            with target.cursor() as cursor:
                cursor.execute(f'SELECT * FROM "{table}"')
                target_rows = cursor.fetchall()
            equal = len(source_rows) == len(target_rows) and digest(source_rows) == digest(target_rows)
            missing += 0 if equal else abs(len(source_rows) - len(target_rows)) or 1
            print(json.dumps({"table": table, "source": len(source_rows), "target": len(target_rows), "hash_equal": equal}))
    source.close()
    print(f"UNEXPLAINED_MISSING_ROWS={missing}")
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
