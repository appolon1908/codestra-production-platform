"""Validation and an isolated durable harness for the JetStream contract."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """The event or transport contract is invalid."""


REQUIRED_EVENT_FIELDS = {
    "event_id", "correlation_id", "tenant_id", "campaign_id", "event_type",
    "schema_version", "producer", "created_at", "idempotency_key",
    "trace_context", "privacy_classification", "payload_hash",
}


def load_contract(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(__file__).with_name("jetstream_contract.json")
    contract = json.loads(source.read_text())
    validate_contract(contract)
    return contract


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("version") != 1 or contract.get("historical_replay_allowed") is not False:
        raise ContractError("contract must be versioned and fail closed for historical replay")
    if set(contract.get("required_event_fields", ())) != REQUIRED_EVENT_FIELDS:
        raise ContractError("canonical event fields are incomplete")
    streams = contract.get("streams", ())
    if len({stream["name"] for stream in streams}) != len(streams):
        raise ContractError("stream names must be unique")
    subjects: set[str] = set()
    for stream in streams:
        if stream["storage"] != "file" or stream["replicas"] < 1:
            raise ContractError("streams must be durable")
        if not stream["deny_delete"] or not stream["deny_purge"]:
            raise ContractError("operator deletion must fail closed")
        if stream["duplicate_window_seconds"] < 120 or stream["max_message_bytes"] > 1048576:
            raise ContractError("deduplication or message-size bound is unsafe")
        for subject in stream["subjects"]:
            if not subject.startswith("codestra.v1.*.*.events.") or subject in subjects:
                raise ContractError("subjects must be tenant/campaign scoped and non-overlapping")
            subjects.add(subject)
    names = {stream["name"] for stream in streams}
    retention = {stream["name"]: stream["retention"] for stream in streams}
    for consumer in contract.get("consumers", ()):
        if consumer["stream"] not in names or consumer["ack_policy"] != "explicit":
            raise ContractError("consumer stream or ACK policy is invalid")
        if consumer["max_deliver"] < 2 or consumer["ack_wait_seconds"] < 1:
            raise ContractError("consumer retry bounds are invalid")
        expected_delivery = "all" if retention[consumer["stream"]] == "workqueue" else "new"
        if consumer["deliver_policy"] != expected_delivery:
            raise ContractError("consumer delivery policy is inconsistent with stream retention")


def validate_event(event: dict[str, Any]) -> str:
    missing = REQUIRED_EVENT_FIELDS - event.keys()
    if missing:
        raise ContractError(f"event fields missing: {sorted(missing)}")
    if event["schema_version"] != 1:
        raise ContractError("unsupported schema version")
    if not event["tenant_id"] or not event["campaign_id"]:
        raise ContractError("tenant and campaign are required")
    payload = event.get("payload", {})
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != event["payload_hash"]:
        raise ContractError("payload hash mismatch")
    return digest


class DurableEventHarness:
    """SQLite-backed isolated proof of effective-once processing semantics."""

    def __init__(self, path: Path, max_deliver: int = 5) -> None:
        self.connection = sqlite3.connect(path)
        self.max_deliver = max_deliver
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS event_inbox (
              event_id TEXT PRIMARY KEY,
              idempotency_key TEXT NOT NULL UNIQUE,
              correlation_id TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              state TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS business_effect (
              correlation_id TEXT PRIMARY KEY,
              event_id TEXT NOT NULL,
              terminal_sequence INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dead_letter (
              event_id TEXT PRIMARY KEY,
              correlation_id TEXT NOT NULL,
              attempts INTEGER NOT NULL,
              failure_class TEXT NOT NULL
            );
            """
        )

    def ingest(self, event: dict[str, Any], sequence: int) -> str:
        validate_event(event)
        try:
            self.connection.execute(
                "INSERT INTO event_inbox(event_id,idempotency_key,correlation_id,payload_hash,sequence) VALUES(?,?,?,?,?)",
                (event["event_id"], event["idempotency_key"], event["correlation_id"], event["payload_hash"], sequence),
            )
            self.connection.commit()
            return "accepted"
        except sqlite3.IntegrityError:
            row = self.connection.execute(
                "SELECT event_id,idempotency_key,correlation_id,payload_hash FROM event_inbox WHERE event_id=? OR idempotency_key=?",
                (event["event_id"], event["idempotency_key"]),
            ).fetchone()
            expected = (
                event["event_id"], event["idempotency_key"],
                event["correlation_id"], event["payload_hash"],
            )
            if row == expected:
                return "duplicate"
            raise ContractError("conflicting idempotency identity")

    def process(self, event_id: str, *, fail: bool = False) -> str:
        with self.connection:
            row = self.connection.execute(
                "SELECT idempotency_key,correlation_id,sequence,attempts,state FROM event_inbox WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if not row:
                raise ContractError("unknown event")
            _key, correlation, sequence, attempts, state = row
            if state in {"acknowledged", "dead_letter"}:
                return state
            attempts += 1
            self.connection.execute("UPDATE event_inbox SET attempts=? WHERE event_id=?", (attempts, event_id))
            if fail:
                if attempts >= self.max_deliver:
                    self.connection.execute(
                        "INSERT OR IGNORE INTO dead_letter VALUES(?,?,?,?)",
                        (event_id, correlation, attempts, "bounded_processing_failure"),
                    )
                    self.connection.execute("UPDATE event_inbox SET state='dead_letter' WHERE event_id=?", (event_id,))
                    return "dead_letter"
                return "retry"
            current = self.connection.execute(
                "SELECT terminal_sequence FROM business_effect WHERE correlation_id=?", (correlation,)
            ).fetchone()
            if current is None:
                self.connection.execute("INSERT INTO business_effect VALUES(?,?,?)", (correlation, event_id, sequence))
            elif sequence > current[0]:
                self.connection.execute(
                    "UPDATE business_effect SET event_id=?,terminal_sequence=? WHERE correlation_id=?",
                    (event_id, sequence, correlation),
                )
            self.connection.execute("UPDATE event_inbox SET state='acknowledged' WHERE event_id=?", (event_id,))
            return "acknowledged"

    def counts(self) -> dict[str, int]:
        return {
            table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("event_inbox", "business_effect", "dead_letter")
        }

    def close(self) -> None:
        self.connection.close()
