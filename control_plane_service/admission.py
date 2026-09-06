"""Fail-closed container entrypoint for all externally delivered channels."""
from __future__ import annotations

import os
import sys


ALWAYS_DISABLED_FLAGS = ("LIVE_SMS_DELIVERY", "LIVE_PSTN_DIALING")


def main(argv: list[str] | None = None) -> None:
    command = list(sys.argv[1:] if argv is None else argv)
    for flag in ALWAYS_DISABLED_FLAGS:
        if os.environ.get(flag) != "false":
            raise SystemExit(f"live-delivery admission denied: {flag} must be exactly false")
    email = os.environ.get("LIVE_EMAIL_DELIVERY")
    email_authorized = (
        email == "true"
        and os.environ.get("CONTROL_PLANE_OUTBOUND_ENABLED") == "true"
        and os.environ.get("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED") == "true"
        and os.environ.get("KLYROW_MODE") == "production"
        and os.environ.get("TELNEXA_MODE", "simulator") == "simulator"
    )
    if email != "false" and not email_authorized:
        raise SystemExit("live-delivery admission denied: LIVE_EMAIL_DELIVERY is not narrowly authorized")
    if not command:
        raise SystemExit("live-delivery admission denied: command is required")
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
