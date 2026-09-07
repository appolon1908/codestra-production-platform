from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import asyncpg

MIGRATIONS = ("0001_realtime_gateway", "0002_canonical_scope")
ROOT = pathlib.Path(__file__).with_name("migrations")


def database_url() -> str:
    with open(os.environ["DATABASE_URL_FILE"], encoding="utf-8") as handle:
        return handle.read().strip()


async def migrate(direction: str) -> None:
    if direction not in {"up", "down"}:
        raise SystemExit("usage: migrate.py up|down")
    connection = await asyncpg.connect(database_url())
    try:
        async with connection.transaction():
            exists = await connection.fetchval(
                "SELECT to_regclass('public.websocket_schema_migrations') IS NOT NULL"
            )
            applied = set()
            if exists:
                applied = {row["version"] for row in await connection.fetch(
                    "SELECT version FROM websocket_schema_migrations"
                )}
                unknown = applied.difference(MIGRATIONS)
                if unknown:
                    raise RuntimeError(f"unknown database migrations: {sorted(unknown)}")
            selected = MIGRATIONS if direction == "up" else tuple(reversed(MIGRATIONS))
            for version in selected:
                if (direction == "up" and version in applied) or (direction == "down" and version not in applied):
                    continue
                sql = (ROOT / f"{version}.{direction}.sql").read_text(encoding="utf-8")
                await connection.execute(sql)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(migrate(sys.argv[1] if len(sys.argv) == 2 else ""))
