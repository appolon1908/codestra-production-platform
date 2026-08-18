"""Notification worker; performs no delivery while communication flags are off."""

from app.core.config import settings
from app.entrypoints.runtime import run_worker


SERVICE = "middleware-notification-worker"
QUEUE = "middleware.notification.v1"


async def cycle() -> dict[str, object]:
    enabled = settings.messaging_enabled or settings.n8n_delivery_enabled
    return {"status": "idle" if enabled else "disabled"}


if __name__ == "__main__":
    run_worker(SERVICE, QUEUE, cycle)
