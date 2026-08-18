"""Report-only reconciliation worker."""

from app.db.session import SessionFactory
from app.entrypoints.runtime import run_worker
from app.workers.reconciliation import reconcile_internal_outbox
from app.workers.quarantine import CLEANUP, cleanup_expired


SERVICE = "middleware-reconciliation-worker"
QUEUE = "middleware.reconciliation.v1"


async def cycle() -> dict[str, object]:
    async with SessionFactory() as session:
        reconciliation = await reconcile_internal_outbox(session)
        try:
            cleanup = await cleanup_expired(session)
        except Exception:
            CLEANUP.labels("failure").inc()
            raise
        return {"reconciliation": reconciliation, "quarantine_cleanup": cleanup}


if __name__ == "__main__":
    run_worker(SERVICE, QUEUE, cycle)
