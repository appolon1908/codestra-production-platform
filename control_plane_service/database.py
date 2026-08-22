from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Iterable


def _database_url() -> str:
    value = os.getenv("CONTROL_PLANE_DATABASE_URL", "")
    path = os.getenv("CONTROL_PLANE_DATABASE_URL_FILE", "")
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
    from psycopg.types.json import Jsonb
    IntegrityError = psycopg.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


def json_value(value: Any) -> Any:
    """Return a value explicitly adapted for the active JSON storage type."""
    if is_postgres():
        return Jsonb(value)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _postgres_sql(sql: str) -> str:
    translated = sql.replace("?", "%s")
    # The embedded test schema uses collision-resistant cp_* names. PostgreSQL
    # exposes the same model as the dedicated control_plane schema.
    mapping = {
        "postal_inbound_event": "control_plane.postal_inbound_event",
        "cp_campaign_email_domain": "control_plane.campaign_email_domain",
        "cp_agent_mailbox": "control_plane.agent_mailbox",
        "cp_mailbox_provisioning_event": "control_plane.mailbox_provisioning_event",
        "cp_campaign_target": "control_plane.campaign_target",
        "cp_extension_assignment": "control_plane.extension_assignment",
        "cp_agent_identity": "control_plane.agent_identity",
        "cp_reconciliation_difference": "control_plane.reconciliation_difference",
        "cp_reconciliation_run": "control_plane.reconciliation_run",
        "cp_event_delivery": "control_plane.event_delivery",
        "cp_sync_result": "control_plane.sync_result",
        "cp_sync_step": "control_plane.sync_step",
        "cp_sync_job": "control_plane.sync_job",
        "cp_dead_letter": "control_plane.dead_letter",
        "cp_idempotency": "control_plane.idempotency",
        "cp_membership": "control_plane.membership",
        "cp_extension": "control_plane.extension",
        "cp_campaign": "control_plane.campaign",
        "cp_agent": "control_plane.agent",
        "cp_event": "control_plane.event",
        "cp_audit": "control_plane.audit",
    }
    for source, target in mapping.items():
        translated = translated.replace(source, target)
    return translated


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
        return self.raw.execute(_postgres_sql(sql) if is_postgres() else sql, params)

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]):
        if not is_postgres():
            return self.raw.executemany(sql, params)
        cursor = self.raw.cursor()
        cursor.executemany(_postgres_sql(sql), params)
        return cursor

    def executescript(self, script: str) -> None:
        if not is_postgres():
            self.raw.executescript(script)
            return
        for statement in script.split(";"):
            statement = statement.strip()
            if statement and not statement.upper().startswith("PRAGMA"):
                self.raw.execute(_postgres_sql(statement))
