#!/usr/bin/env python3
"""Run the fail-closed JetStream maximum-delivery forwarding worker."""

from __future__ import annotations

import asyncio
import os
import signal
import ssl
from pathlib import Path

import nats

from eventing.dead_letter import (
    bind_dead_letter_advisory_consumer,
    process_next_dead_letter_advisory,
)


def protected_value(path: str) -> str:
    source = Path(path)
    if not source.is_file() or source.stat().st_mode & 0o077:
        raise RuntimeError(f"protected configuration is missing or unsafe: {path}")
    return source.read_text().strip()


async def run() -> None:
    if os.getenv("JETSTREAM_DLQ_WORKER_ENABLED", "false").lower() != "true":
        raise RuntimeError("JetStream DLQ worker is disabled")
    url = protected_value(os.environ["NATS_URL_FILE"])
    if not url.startswith("tls://"):
        raise RuntimeError("production NATS transport must use TLS")
    tls = ssl.create_default_context(cafile=os.environ["NATS_CA_FILE"])
    tls.load_cert_chain(
        os.environ["NATS_CLIENT_CERT_FILE"], os.environ["NATS_CLIENT_KEY_FILE"]
    )
    connection = await nats.connect(
        servers=[url],
        tls=tls,
        name="codestra-jetstream-dlq-worker",
        connect_timeout=5,
        max_reconnect_attempts=-1,
        reconnect_time_wait=2,
    )
    jetstream = connection.jetstream()
    subscription = await bind_dead_letter_advisory_consumer(jetstream)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for event in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(event, stopped.set)
    try:
        while not stopped.is_set():
            try:
                await process_next_dead_letter_advisory(
                    jetstream, subscription, timeout=1
                )
            except nats.errors.TimeoutError:
                continue
    finally:
        await connection.drain()


if __name__ == "__main__":
    asyncio.run(run())
