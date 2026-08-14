#!/usr/bin/env python3
"""Apply the reviewed Codestra JetStream contract to an explicit NATS URL."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import nats
from nats.js import api

from eventing.contract import load_contract


RETENTION = {
    "limits": api.RetentionPolicy.LIMITS,
    "workqueue": api.RetentionPolicy.WORK_QUEUE,
}
DELIVERY = {
    "all": api.DeliverPolicy.ALL,
    "new": api.DeliverPolicy.NEW,
}


async def apply_contract(server: str, contract_path: Path | None = None) -> None:
    contract = load_contract(contract_path)
    client = await nats.connect(server, connect_timeout=2)
    try:
        manager = client.jetstream()
        for item in contract["streams"]:
            config = api.StreamConfig(
                name=item["name"],
                subjects=item["subjects"],
                retention=RETENTION[item["retention"]],
                storage=api.StorageType.FILE,
                num_replicas=item["replicas"],
                max_age=item["max_age_seconds"],
                duplicate_window=item["duplicate_window_seconds"],
                max_msg_size=item["max_message_bytes"],
                deny_delete=item["deny_delete"],
                deny_purge=item["deny_purge"],
            )
            try:
                await manager.stream_info(item["name"])
                await manager.update_stream(config=config)
            except nats.js.errors.NotFoundError:
                await manager.add_stream(config=config)
        for item in contract["consumers"]:
            config = api.ConsumerConfig(
                durable_name=item["durable"],
                filter_subject=item["filter_subject"],
                ack_policy=api.AckPolicy.EXPLICIT,
                ack_wait=item["ack_wait_seconds"],
                max_deliver=item["max_deliver"],
                backoff=item["backoff_seconds"],
                replay_policy=api.ReplayPolicy.INSTANT,
                deliver_policy=DELIVERY[item["deliver_policy"]],
            )
            try:
                before = await manager.consumer_info(item["stream"], item["durable"])
            except nats.js.errors.NotFoundError:
                await manager.add_consumer(stream=item["stream"], config=config)
            else:
                existing_expected = {
                    "filter_subject": config.filter_subject,
                    "deliver_policy": config.deliver_policy,
                    "replay_policy": config.replay_policy,
                    "ack_policy": config.ack_policy,
                    "ack_wait": config.backoff[0] if config.backoff else config.ack_wait,
                    "max_deliver": config.max_deliver,
                    "backoff": config.backoff,
                }
                existing_mismatches = {
                    field: (wanted, getattr(before.config, field))
                    for field, wanted in existing_expected.items()
                    if getattr(before.config, field) != wanted
                }
                if existing_mismatches:
                    raise RuntimeError(
                        f"consumer {item['stream']}/{item['durable']} differs from contract: {existing_mismatches}"
                    )
            actual = (await manager.consumer_info(item["stream"], item["durable"])).config
            expected = {
                "filter_subject": config.filter_subject,
                "ack_policy": config.ack_policy,
                # JetStream defines the first backoff value as the effective
                # acknowledgement wait whenever a backoff schedule is set.
                "ack_wait": config.backoff[0] if config.backoff else config.ack_wait,
                "max_deliver": config.max_deliver,
                "backoff": config.backoff,
                "replay_policy": config.replay_policy,
                "deliver_policy": config.deliver_policy,
            }
            mismatches = {
                field: (wanted, getattr(actual, field))
                for field, wanted in expected.items()
                if getattr(actual, field) != wanted
            }
            if mismatches:
                raise RuntimeError(
                    f"consumer {item['stream']}/{item['durable']} differs from contract: {mismatches}"
                )
    finally:
        await client.drain()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--contract", type=Path)
    args = parser.parse_args()
    if not args.server.startswith("nats://"):
        parser.error("an explicit nats:// URL is required")
    asyncio.run(apply_contract(args.server, args.contract))
    print("jetstream_contract=applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
