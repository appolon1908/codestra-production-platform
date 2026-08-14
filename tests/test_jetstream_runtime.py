from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import socket
import subprocess
import time

import nats
import pytest
from nats.js import api

from eventing.dead_letter import (
    bind_dead_letter_advisory_consumer,
    process_next_dead_letter_advisory,
)
from tools.apply_jetstream_contract import apply_contract


pytestmark = pytest.mark.skipif(shutil.which("nats-server") is None, reason="nats-server unavailable")


def free_port() -> int:
    with socket.socket() as value:
        value.bind(("127.0.0.1", 0))
        return value.getsockname()[1]


def start_server(port: int, store, log):
    process = subprocess.Popen(
        ["nats-server", "-js", "-a", "127.0.0.1", "-p", str(port), "-sd", str(store)],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(100):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return process
        time.sleep(0.02)
    process.terminate()
    raise RuntimeError("isolated NATS did not start")


def payload():
    body = {"state": "answered", "synthetic": True}
    return json.dumps({
        "event_id": "evt-runtime-1",
        "correlation_id": "corr-runtime-1",
        "tenant_id": "synthetic-tenant",
        "campaign_id": "TEST_SYN",
        "event_type": "call.state",
        "schema_version": 1,
        "producer": "isolated-fixture",
        "created_at": "2026-08-14T17:00:00Z",
        "idempotency_key": "runtime-call-1",
        "trace_context": "00-00000000000000000000000000000001-0000000000000001-01",
        "privacy_classification": "synthetic",
        "payload_hash": hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "payload": body,
    }, sort_keys=True).encode()


def test_isolated_jetstream_dedup_redelivery_and_restart(tmp_path):
    async def scenario():
        port = free_port()
        log = (tmp_path / "nats.log").open("wb")
        server = start_server(port, tmp_path / "store", log)
        url = f"nats://127.0.0.1:{port}"
        try:
            await apply_contract(url)
            client = await nats.connect(url)
            js = client.jetstream()
            subject = "codestra.v1.synthetic-tenant.TEST_SYN.events.ingress"
            first = await js.publish(subject, payload(), headers={"Nats-Msg-Id": "evt-runtime-1"})
            duplicate = await js.publish(subject, payload(), headers={"Nats-Msg-Id": "evt-runtime-1"})
            assert first.duplicate is None or first.duplicate is False
            assert duplicate.duplicate is True
            subscription = await js.pull_subscribe(subject, durable="middleware-ingress-v1", stream="CODESTRA_INGRESS_V1")
            message = (await subscription.fetch(1, timeout=2))[0]
            await message.nak()
            redelivered = (await subscription.fetch(1, timeout=7))[0]
            assert redelivered.metadata.num_delivered == 2
            await redelivered.ack_sync()
            await client.drain()
            server.terminate()
            server.wait(timeout=5)
            server = start_server(port, tmp_path / "store", log)
            client = await nats.connect(url)
            info = await client.jetstream().stream_info("CODESTRA_INGRESS_V1")
            assert info.state.messages == 1
            await client.drain()
        finally:
            server.terminate()
            server.wait(timeout=5)
            log.close()

    asyncio.run(scenario())


def test_existing_consumer_drift_fails_closed(tmp_path):
    async def scenario():
        port = free_port()
        log = (tmp_path / "reconcile.log").open("wb")
        server = start_server(port, tmp_path / "store-reconcile", log)
        url = f"nats://127.0.0.1:{port}"
        try:
            await apply_contract(url)
            client = await nats.connect(url)
            js = client.jetstream()
            from nats.js import api

            await js.delete_consumer("CODESTRA_INGRESS_V1", "middleware-ingress-v1")
            await js.add_consumer(
                "CODESTRA_INGRESS_V1",
                config=api.ConsumerConfig(
                    durable_name="middleware-ingress-v1",
                    filter_subject="codestra.v1.*.*.events.ingress",
                    ack_policy=api.AckPolicy.EXPLICIT,
                    ack_wait=1,
                    max_deliver=2,
                    deliver_policy=api.DeliverPolicy.NEW,
                ),
            )
            await client.drain()
            import pytest

            with pytest.raises(RuntimeError, match="differs from contract"):
                await apply_contract(url)
        finally:
            server.terminate()
            server.wait(timeout=5)
            log.close()

    asyncio.run(scenario())


def test_max_delivery_advisory_is_forwarded_once_to_dlq(tmp_path):
    async def scenario():
        port = free_port()
        log = (tmp_path / "dead-letter.log").open("wb")
        server = start_server(port, tmp_path / "store-dead-letter", log)
        url = f"nats://127.0.0.1:{port}"
        try:
            await apply_contract(url)
            client = await nats.connect(url)
            js = client.jetstream()
            await js.delete_consumer("CODESTRA_INGRESS_V1", "middleware-ingress-v1")
            await js.add_consumer(
                "CODESTRA_INGRESS_V1",
                config=api.ConsumerConfig(
                    durable_name="middleware-ingress-v1",
                    filter_subject="codestra.v1.*.*.events.ingress",
                    ack_policy=api.AckPolicy.EXPLICIT,
                    ack_wait=0.1,
                    max_deliver=2,
                    deliver_policy=api.DeliverPolicy.ALL,
                ),
            )
            subject = "codestra.v1.synthetic-tenant.TEST_SYN.events.ingress"
            await js.publish(subject, payload(), headers={"Nats-Msg-Id": "evt-dlq-1"})
            subscription = await js.pull_subscribe(
                subject, durable="middleware-ingress-v1", stream="CODESTRA_INGRESS_V1"
            )
            first = (await subscription.fetch(1, timeout=2))[0]
            await first.nak()
            second = (await subscription.fetch(1, timeout=2))[0]
            await second.nak()
            with pytest.raises(nats.errors.TimeoutError):
                await subscription.fetch(1, timeout=0.5)
            # The forwarding worker was deliberately absent while the advisory
            # was emitted. The persistent advisory stream must retain it.
            advisory_info = await js.stream_info("CODESTRA_DLQ_ADVISORIES_V1")
            assert advisory_info.state.messages == 1
            worker = await bind_dead_letter_advisory_consumer(js)
            assert await process_next_dead_letter_advisory(
                js, worker, timeout=2
            ) == "forwarded"
            info = await js.stream_info("CODESTRA_DEAD_LETTER_V1")
            assert info.state.messages == 1
            message = await js.get_msg("CODESTRA_DEAD_LETTER_V1", seq=1)
            envelope = json.loads(message.data)
            assert envelope["failure"]["failure_class"] == "max_deliver_exhausted"
            assert envelope["failure"]["delivery_attempts"] == 2
            assert envelope["failure"]["failed_at"].endswith("+00:00")
            await client.drain()
        finally:
            server.terminate()
            server.wait(timeout=5)
            log.close()

    asyncio.run(scenario())
