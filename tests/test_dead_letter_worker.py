from __future__ import annotations

import asyncio
import json

import pytest

from eventing.dead_letter import (
    DeadLetterError,
    bind_dead_letter_advisory_consumer,
    process_next_dead_letter_advisory,
)


class Message:
    def __init__(self, data: bytes):
        self.data = data
        self.acked = False
        self.nacked = False

    async def ack(self):
        self.acked = True

    async def nak(self):
        self.nacked = True


class Subscription:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.fetches = 0

    async def fetch(self, count, timeout):
        assert count == 1
        assert timeout == 0.01
        self.fetches += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return [outcome]


class JetStream:
    def __init__(self, subscription):
        self.subscription = subscription
        self.binds = []

    async def pull_subscribe_bind(self, durable, stream):
        self.binds.append((durable, stream))
        return self.subscription

    async def get_msg(self, stream, seq):
        class Original:
            subject = "codestra.v1.synthetic.TEST_SYN.events.ingress"
            data = json.dumps({"event_id": f"evt-{seq}"}).encode()

        return Original()

    async def publish(self, subject, data, headers):
        class Ack:
            duplicate = False

        return Ack()


def advisory(sequence: int = 1) -> bytes:
    return json.dumps(
        {
            "stream": "CODESTRA_INGRESS_V1",
            "consumer": "middleware-ingress-v1",
            "stream_seq": sequence,
            "deliveries": 5,
        }
    ).encode()


def test_worker_reuses_one_binding_across_idle_and_message_cycles() -> None:
    async def scenario():
        first = Message(advisory(1))
        second = Message(advisory(2))
        subscription = Subscription([TimeoutError(), TimeoutError(), first, second])
        js = JetStream(subscription)
        worker = await bind_dead_letter_advisory_consumer(js)

        for _ in range(2):
            with pytest.raises(TimeoutError):
                await process_next_dead_letter_advisory(js, worker, timeout=0.01)
        assert await process_next_dead_letter_advisory(js, worker, timeout=0.01) == "forwarded"
        assert await process_next_dead_letter_advisory(js, worker, timeout=0.01) == "forwarded"

        assert len(js.binds) == 1
        assert subscription.fetches == 4
        assert first.acked and second.acked

    asyncio.run(scenario())


def test_forwarding_failure_naks_without_ack() -> None:
    async def scenario():
        message = Message(b"not-json")
        subscription = Subscription([message])
        js = JetStream(subscription)
        worker = await bind_dead_letter_advisory_consumer(js)
        with pytest.raises(DeadLetterError):
            await process_next_dead_letter_advisory(js, worker, timeout=0.01)
        assert message.nacked is True
        assert message.acked is False

    asyncio.run(scenario())


def test_worker_restart_rebinds_existing_durable_consumer() -> None:
    async def scenario():
        js = JetStream(Subscription([]))
        await bind_dead_letter_advisory_consumer(js)
        await bind_dead_letter_advisory_consumer(js)
        assert js.binds == [
            ("middleware-dlq-advisory-v1", "CODESTRA_DLQ_ADVISORIES_V1"),
            ("middleware-dlq-advisory-v1", "CODESTRA_DLQ_ADVISORIES_V1"),
        ]

    asyncio.run(scenario())
