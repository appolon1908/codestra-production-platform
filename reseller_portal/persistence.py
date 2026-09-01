from __future__ import annotations

import json
from dataclasses import asdict
from threading import RLock

import psycopg

from .core import MemoryStore


class PostgresState:
    """Single-worker durable state repository; PostgreSQL is authoritative."""
    def __init__(self, dsn: str):
        self.dsn, self.lock = dsn, RLock()
        with psycopg.connect(dsn) as conn:
            conn.execute("CREATE SCHEMA IF NOT EXISTS reseller")
            conn.execute("CREATE TABLE IF NOT EXISTS reseller.portal_state (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), payload jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())")

    def load(self) -> MemoryStore:
        with psycopg.connect(self.dsn) as conn:
            row=conn.execute("SELECT payload FROM reseller.portal_state WHERE singleton=true").fetchone()
        data=row[0] if row else {}
        allowed=set(MemoryStore.__dataclass_fields__)
        return MemoryStore(**{k:v for k,v in data.items() if k in allowed})

    def save(self, store: MemoryStore) -> None:
        payload=json.dumps(asdict(store))
        with self.lock, psycopg.connect(self.dsn) as conn:
            conn.execute("INSERT INTO reseller.portal_state(singleton,payload) VALUES(true,%s::jsonb) ON CONFLICT(singleton) DO UPDATE SET payload=excluded.payload,updated_at=now()",(payload,))

    def bootstrap_empty(self, store: MemoryStore) -> None:
        """Create the initial authority exactly once; never overwrite state."""
        payload=json.dumps(asdict(store))
        with psycopg.connect(self.dsn) as conn:
            inserted=conn.execute(
                "INSERT INTO reseller.portal_state(singleton,payload) VALUES(true,%s::jsonb) ON CONFLICT(singleton) DO NOTHING RETURNING singleton",
                (payload,),
            ).fetchone()
            if not inserted:
                raise RuntimeError("portal authority is already initialized")
