"""One-shot, database-authenticated bootstrap for the first portal owner."""
import os

from .core import MemoryStore, PortalService
from .persistence import PostgresState


def main() -> None:
    if os.getenv("PORTAL_BOOTSTRAP_CONFIRMATION") != "BOOTSTRAP_EMPTY_RESELLER_AUTHORITY":
        raise SystemExit("explicit bootstrap confirmation required")
    required = {name: os.getenv(name, "").strip() for name in (
        "DATABASE_URL", "PORTAL_BOOTSTRAP_ORGANIZATION", "PORTAL_BOOTSTRAP_SUBJECT", "PORTAL_BOOTSTRAP_EMAIL"
    )}
    if not all(required.values()):
        raise SystemExit("bootstrap inputs are incomplete")
    store=MemoryStore(); service=PortalService(store)
    tenant=service.organization(required["PORTAL_BOOTSTRAP_ORGANIZATION"])
    service.user(tenant["id"],required["PORTAL_BOOTSTRAP_SUBJECT"],required["PORTAL_BOOTSTRAP_EMAIL"],"owner")
    PostgresState(required["DATABASE_URL"]).bootstrap_empty(store)
    print("PORTAL_BOOTSTRAP=PASS")


if __name__ == "__main__":
    main()
