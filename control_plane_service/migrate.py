from __future__ import annotations

import os
import sqlite3

import psycopg

from .core import Store
from .database import DATABASE_URL


TABLES = [
    "integrations", "circuits", "audit", "contacts", "preferences", "suppressions",
    "crm_customers", "crm_objects", "crm_idempotency", "crm_audit",
    "crawler_jobs", "crawler_results", "events", "event_deliveries",
    "messages", "message_events", "usage_meter",
]


def main() -> None:
    source = os.environ["SQLITE_SOURCE"]
    Store(source).initialize()
    sqlite = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    sqlite.row_factory = sqlite3.Row
    with psycopg.connect(DATABASE_URL) as target:
        with target.cursor() as cursor:
            cursor.execute("TRUNCATE " + ",".join(TABLES) + " CASCADE")
            for table in TABLES:
                rows = sqlite.execute(f'SELECT * FROM "{table}"').fetchall()
                columns = [item[1] for item in sqlite.execute(f'PRAGMA table_info("{table}")')]
                if rows:
                    names = ",".join(f'"{name}"' for name in columns)
                    values = ",".join(["%s"] * len(columns))
                    cursor.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({values})', [tuple(row) for row in rows])
                print(f"{table}={len(rows)}")
    sqlite.close()


if __name__ == "__main__":
    main()
