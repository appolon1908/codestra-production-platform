"""Durable effective-once sink used for Odoo/n8n/callback certification."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class IntegrationError(RuntimeError):
    pass


class EffectiveOnceSink:
    def __init__(self, path: Path, namespace: str) -> None:
        if namespace not in {"odoo_test", "n8n_test", "callback_test"}:
            raise IntegrationError("production namespace is prohibited in isolated certification")
        self.namespace = namespace
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS delivery (
              event_id TEXT NOT NULL,
              sink TEXT NOT NULL,
              correlation_id TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              state TEXT NOT NULL DEFAULT 'pending',
              PRIMARY KEY(event_id, sink)
            );
            CREATE TABLE IF NOT EXISTS effect (
              sink TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,
              correlation_id TEXT NOT NULL,
              terminal_sequence INTEGER NOT NULL,
              payload_hash TEXT NOT NULL,
              PRIMARY KEY(sink, idempotency_key)
            );
            """
        )

    def enqueue(self, event: dict) -> str:
        required = {"event_id", "correlation_id", "idempotency_key", "payload_hash", "sequence"}
        if required - event.keys():
            raise IntegrationError("event contract is incomplete")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO delivery(event_id,sink,correlation_id,idempotency_key,payload_hash,sequence) VALUES(?,?,?,?,?,?)",
                    (event["event_id"], self.namespace, event["correlation_id"], event["idempotency_key"], event["payload_hash"], event["sequence"]),
                )
            return "accepted"
        except sqlite3.IntegrityError:
            row = self.db.execute(
                "SELECT correlation_id,idempotency_key,payload_hash,sequence FROM delivery WHERE event_id=? AND sink=?",
                (event["event_id"], self.namespace),
            ).fetchone()
            if row == (event["correlation_id"], event["idempotency_key"], event["payload_hash"], event["sequence"]):
                return "duplicate"
            raise IntegrationError("conflicting duplicate")

    def deliver(self, event: dict, *, unavailable: bool = False) -> str:
        with self.db:
            row = self.db.execute(
                "SELECT state,correlation_id,idempotency_key,payload_hash,sequence FROM delivery WHERE event_id=? AND sink=?",
                (event["event_id"], self.namespace),
            ).fetchone()
            if row is None:
                raise IntegrationError("event was not durably enqueued")
            durable_identity = row[1:]
            supplied_identity = (
                event["correlation_id"], event["idempotency_key"],
                event["payload_hash"], event["sequence"],
            )
            if durable_identity != supplied_identity:
                raise IntegrationError("delivery identity differs from durable event")
            if row[0] == "delivered":
                return "duplicate_suppressed"
            self.db.execute(
                "UPDATE delivery SET attempts=attempts+1 WHERE event_id=? AND sink=?",
                (event["event_id"], self.namespace),
            )
            if unavailable:
                return "retry"
            current = self.db.execute(
                "SELECT correlation_id,terminal_sequence,payload_hash FROM effect WHERE sink=? AND idempotency_key=?",
                (self.namespace, event["idempotency_key"]),
            ).fetchone()
            if current is None:
                self.db.execute(
                    "INSERT INTO effect VALUES(?,?,?,?,?)",
                    (self.namespace, event["idempotency_key"], event["correlation_id"], event["sequence"], event["payload_hash"]),
                )
            elif event["sequence"] > current[1]:
                if event["correlation_id"] != current[0]:
                    raise IntegrationError("newer effect correlation identity conflicts")
                self.db.execute(
                    "UPDATE effect SET terminal_sequence=?,payload_hash=? WHERE sink=? AND idempotency_key=?",
                    (event["sequence"], event["payload_hash"], self.namespace, event["idempotency_key"]),
                )
            elif event["sequence"] == current[1] and (
                event["correlation_id"] != current[0] or event["payload_hash"] != current[2]
            ):
                raise IntegrationError("equal-sequence effect identity conflicts")
            self.db.execute(
                "UPDATE delivery SET state='delivered' WHERE event_id=? AND sink=?",
                (event["event_id"], self.namespace),
            )
            return "delivered"

    def counts(self) -> tuple[int, int]:
        return (
            self.db.execute("SELECT COUNT(*) FROM delivery").fetchone()[0],
            self.db.execute("SELECT COUNT(*) FROM effect").fetchone()[0],
        )
