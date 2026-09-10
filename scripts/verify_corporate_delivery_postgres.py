#!/usr/bin/env python3
"""Exercise migration 007 on a dedicated loopback CI database, never a runtime DB."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    dsn = os.environ["CONTROL_PLANE_DATABASE_URL"]
    target = urlsplit(dsn)
    if (
        os.getenv("CORPORATE_DISPOSABLE_DATABASE") != "YES"
        or target.scheme != "postgresql"
        or target.hostname != "127.0.0.1"
        or target.path != "/corporate_delivery_ci"
        or target.query
        or target.fragment
    ):
        raise SystemExit("DISPOSABLE_DATABASE_REQUIRED")
    import psycopg

    from control_plane_service import automation, database
    from control_plane_service.calling_ingress import IngressError, persist
    from control_plane_service.core import Store

    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(
            "CREATE ROLE codestra_control_plane_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
        )
        for name in ("000_runtime_store.sql", "006_delivery_leases_and_realtime.sql"):
            admin.execute((root / "migrations/control_plane" / name).read_text())
        admin.execute(
            "INSERT INTO automation_executions VALUES ('legacy','legacy-event','legacy-flow','legacy-hash','COMPLETED','[]','legacy-correlation','legacy-attempt','earlier','earlier','earlier')"
        )
        migration = (
            root / "migrations/control_plane/007_corporate_delivery_receipts.sql"
        ).read_text()
        admin.execute(migration)
        admin.execute(
            migration
        )  # Repeat application is idempotent; original mappings survive.
        assert (
            admin.execute(
                "SELECT COUNT(*) FROM automation_execution_attempts WHERE execution_id='legacy-attempt'"
            ).fetchone()[0]
            == 1
        )
        admin.execute(
            "GRANT SELECT,INSERT,UPDATE ON events,event_deliveries,integrations,circuits TO codestra_control_plane_runtime"
        )
        assert not admin.execute(
            "SELECT has_table_privilege('codestra_control_plane_runtime','calling_ingress_receipts','UPDATE')"
        ).fetchone()[0]
        assert not admin.execute(
            "SELECT has_table_privilege('codestra_control_plane_runtime','calling_ingress_receipts','DELETE')"
        ).fetchone()[0]
    # Exercise the real driver under the limited runtime role, not the schema owner.
    database.DATABASE_URL = dsn + "?options=-crole%3Dcodestra_control_plane_runtime"
    store = Store("unused-on-postgres")
    value = {
        "tenant_id": "ci-tenant",
        "event_type": "telephony.call.ringing.v1",
        "event_version": "1.0",
        "idempotency_key": "ci-calling-event",
        "correlation_id": "ci-correlation",
        "occurred_at": "2026-09-07T00:00:00Z",
        "payload": {"event_id": "ci-event"},
    }
    raw = json.dumps(value, sort_keys=True).encode()
    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(
            pool.map(lambda _: persist(store, value, raw, "a" * 64), range(12))
        )
    assert all(receipt == receipts[0] for receipt in receipts)
    try:
        persist(store, value, raw + b" ", "a" * 64)
    except IngressError as exc:
        assert exc.code == "IDEMPOTENCY_CONFLICT"
    else:
        raise AssertionError("changed-byte retry was accepted")
    with store.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM calling_ingress_receipts"
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) AS n FROM event_deliveries").fetchone()[
                "n"
            ]
            == 3
        )
    document = dict(
        schema_version="1",
        event_id="automation-ci-event",
        event_type="customer.created",
        correlation_id="automation-correlation",
        idempotency_key="automation-ci-key",
        tenant_id="ci-tenant",
        business_unit_id="ci-unit",
        campaign_id="ci-campaign",
        entity_type="customer",
        entity_id="ci-customer",
        actor_type="SYSTEM",
        actor_id="middleware",
        occurred_at="2026-09-07T00:00:00Z",
        automation_key="customer-created",
        payload={},
    )
    calls = []

    def no_effect(action, _value, request_hash):
        calls.append((action, request_hash))
        return {"status": "COMPLETED", "action": action}

    automation._invoke_action = no_effect
    for attempt in ("pg-attempt-1", "pg-attempt-2"):
        automation.execute_automation(
            store, {**document, "orchestration_execution_id": attempt}, "ci-tenant"
        )
        result = dict(
            event_id=document["event_id"],
            correlation_id=document["correlation_id"],
            idempotency_key="result-" + attempt,
            workflow_key="customer-created",
            execution_id=attempt,
            status="COMPLETED",
            actions=[{"type": "crm.customer.synchronize"}],
            completed_at="2026-09-07T00:00:01Z",
        )
        assert not automation.record_execution_result(
            store, result, "ci-tenant"
        ).duplicate
        assert automation.record_execution_result(store, result, "ci-tenant").duplicate
    assert len(calls) == 1
    with store.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM automation_execution_attempts WHERE tenant_id='ci-tenant'"
            ).fetchone()["n"]
            == 2
        )
    print("CORPORATE_POSTGRES_CONCURRENCY_MIGRATION_AND_RETRY=PASS")
    print("EXTERNAL_ACTION_CALLS=0")


if __name__ == "__main__":
    main()
