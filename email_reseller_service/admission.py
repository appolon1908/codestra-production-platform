"""Fail-closed entrypoint for the email reseller runtime."""
from __future__ import annotations

import os
import sys


DISABLED_DELIVERY_FLAGS = (
    "LIVE_SMS_DELIVERY",
    "LIVE_EMAIL_DELIVERY",
    "LIVE_PSTN_DIALING",
)


def main(argv: list[str] | None = None) -> None:
    command = list(sys.argv[1:] if argv is None else argv)
    for flag in DISABLED_DELIVERY_FLAGS:
        if os.environ.get(flag) != "false":
            raise SystemExit(f"live-delivery admission denied: {flag} must be exactly false")
    if not command:
        raise SystemExit("live-delivery admission denied: command is required")
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
