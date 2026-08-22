#!/usr/bin/env python3
"""Validate the production middleware's complete fail-closed override."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


REQUIRED_FLAGS = {
    "SEND_EVENTS",
    "ENABLE_EXTERNAL_DELIVERY",
    "ODOO_DELIVERY_ENABLED",
    "CALLBACK_DISPATCH",
    "ENABLE_VICIDIAL_WRITES",
    "LIVE_WRITE",
    "ODOO_WRITE",
    "N8N_DELIVERY_ENABLED",
    "PRODUCTION_DIALING",
    "LIVE_CALL_CONTROL",
    "GENERAL_AI_DIALING",
}


def validate(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"services"}:
        raise ValueError("override must contain only services")
    services = document["services"]
    if not isinstance(services, dict) or set(services) != {"middleware"}:
        raise ValueError("override must target only middleware")
    middleware = services["middleware"]
    if not isinstance(middleware, dict) or set(middleware) != {"environment"}:
        raise ValueError("middleware override must contain only environment")
    environment = middleware["environment"]
    if not isinstance(environment, dict) or set(environment) != REQUIRED_FLAGS:
        raise ValueError("override flag set is incomplete or contains extras")
    if any(value != "false" for value in environment.values()):
        raise ValueError("every fail-closed flag must be the quoted string false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    validate(args.path)
    print("FAIL_CLOSED_OVERRIDE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
