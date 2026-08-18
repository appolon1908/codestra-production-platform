"""Real PostgreSQL concurrency proof for inclusive campaign ranges."""

import asyncio
import os
import uuid

import asyncpg


RUN_ID = "concurrency-" + uuid.uuid4().hex
INSERT = """
INSERT INTO campaign_extension_allocation
(id,campaign_id,campaign_number,allocation_public_id,extension_start,
 extension_end,created_by,policy_hash,source_change_id)
VALUES($1,$2,$3,$4,$5,$6,'concurrency-test',$7,$8)
"""


async def insert(pool, name, number, start, end, delay=0):
    async with pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute(
                INSERT,
                uuid.uuid4(),
                f"{RUN_ID}-{name}",
                number,
                f"ALLOC-{RUN_ID}-{name}",
                start,
                end,
                "c" * 64,
                RUN_ID,
            )
            await asyncio.sleep(delay)
            await transaction.commit()
            return "PASS"
        except (
            asyncpg.DeadlockDetectedError,
            asyncpg.ExclusionViolationError,
        ):
            await transaction.rollback()
            return "OVERLAP"


async def main():
    database_url = os.environ["TEST_DATABASE_URL"]
    assert "diag" in database_url or "rehearsal" in database_url
    pool = await asyncpg.create_pool(database_url)
    exact = await asyncio.gather(
        insert(pool, "EXACT1", 9000, 9000, 9099, 0.1),
        insert(pool, "EXACT2", 9100, 9000, 9099),
    )
    assert sorted(exact) == ["OVERLAP", "PASS"]
    partial = await asyncio.gather(
        insert(pool, "PART1", 9200, 9100, 9199, 0.1),
        insert(pool, "PART2", 9300, 9199, 9298),
    )
    assert sorted(partial) == ["OVERLAP", "PASS"]
    contained = await asyncio.gather(
        insert(pool, "OUTER", 9400, 9300, 9399, 0.1),
        insert(pool, "INNER", 9500, 9320, 9330),
    )
    assert sorted(contained) == ["OVERLAP", "PASS"]
    adjacent = await asyncio.gather(
        insert(pool, "ADJ1", 9600, 9400, 9499, 0.1),
        insert(pool, "ADJ2", 9700, 9500, 9599),
    )
    assert adjacent == ["PASS", "PASS"]
    many = await asyncio.gather(
        *[
            insert(
                pool,
                f"BLOCK{offset}",
                9800 + (offset * 100),
                9600 + (offset * 10),
                9609 + (offset * 10),
            )
            for offset in range(5)
        ]
    )
    assert many == ["PASS"] * 5
    async with pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        await connection.execute(
            INSERT,
            uuid.uuid4(),
            f"{RUN_ID}-ROLLBACK",
            10300,
            f"ALLOC-{RUN_ID}-ROLLBACK",
            9700,
            9799,
            "c" * 64,
            RUN_ID,
        )
        await transaction.rollback()
    assert await insert(pool, "AFTERROLLBACK", 10400, 9700, 9799) == "PASS"
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE campaign_extension_allocation"
            " SET allocation_status='RETIRED' WHERE campaign_id=$1",
            f"{RUN_ID}-AFTERROLLBACK",
        )
    assert await insert(pool, "REUSE", 10500, 9700, 9799) == "OVERLAP"
    async with pool.acquire() as connection:
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM campaign_extension_allocation"
                " WHERE source_change_id=$1",
                RUN_ID,
            )
            == 11
        )
    await pool.close()
    print("CONCURRENT_OVERLAP_GATE=PASS")
    print("CONCURRENT_ADJACENT_GATE=PASS")
    print("RACE_CONDITION_GATE=PASS")
    print("TRANSACTION_ROLLBACK_GATE=PASS")
    print("RETIRED_RANGE_NON_REUSE_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(main())
