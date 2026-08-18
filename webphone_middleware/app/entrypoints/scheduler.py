"""Lease recovery and maintenance scheduler."""

from app.core.config import settings
from app.entrypoints.runtime import run_worker
from app.workers.scheduler import maintenance_once


SERVICE = "middleware-scheduler"
QUEUE = "middleware.scheduler.v1"


async def cycle() -> dict[str, object]:
    if not settings.outbox_worker_enabled:
        return {"status": "disabled"}
    return await maintenance_once()


if __name__ == "__main__":
    run_worker(SERVICE, QUEUE, cycle)
