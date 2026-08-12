#!/usr/bin/env python3
"""Fail closed when the staging adapter runtime is unsafe."""
from __future__ import annotations

import os
from pathlib import Path

FALSE_FLAGS = (
    "ENABLE_PROVISIONING",
    "ENABLE_AGENT_SYNC",
    "ENABLE_IVR_CALLBACKS",
    "ENABLE_WARM_TRANSFER",
    "ENABLE_LIVE_CALL_CONTROL",
    "ENABLE_IVR_ROUTING",
    "ENABLE_PRODUCTION_DIALING",
    "ENABLE_EMAIL_DELIVERY",
    "ENABLE_SMS_DELIVERY",
    "ENABLE_AI_ACTIONS",
)

for name in FALSE_FLAGS:
    if os.environ.get(name, "").lower() != "false":
        raise SystemExit("{} must be false in staging deployment".format(name))

write_gate = os.environ.get("ENABLE_VICIDIAL_WRITES", "").lower()
lead_gate = os.environ.get("ENABLE_LEAD_PUBLICATION", "").lower()
if write_gate not in {"true", "false"} or lead_gate not in {"true", "false"}:
    raise SystemExit("synthetic write gates must be explicit booleans")
if write_gate != lead_gate:
    raise SystemExit("synthetic write gates must change together")
if os.environ.get("SYNTHETIC_CAMPAIGN") != "TEST_SYN":
    raise SystemExit("synthetic campaign must be TEST_SYN")
if os.environ.get("SYNTHETIC_LIST_ID") != "9001":
    raise SystemExit("synthetic list must be 9001")
if os.environ.get("SYNTHETIC_PHONE_NUMBER") != "5550100199":
    raise SystemExit("synthetic number mismatch")

if os.environ.get("CODESTRA_ADAPTER_BACKEND") != "mysql":
    raise SystemExit("read-only staging deployment requires mysql backend")
if os.environ.get("AUTHORIZED_PRIVATE_SOURCE_IP") != "10.40.0.1":
    raise SystemExit("authorized private source mismatch")
if os.environ.get("MIDDLEWARE_BASE_URL") != "https://api.codestra.agency":
    raise SystemExit("middleware URL mismatch")
if os.environ.get("KEYCLOAK_ISSUER_URL") != "https://auth.codestra.agency":
    raise SystemExit("Keycloak issuer mismatch")

secret = Path(os.environ["CODESTRA_ADAPTER_HMAC_FILE"])
if not secret.is_file() or secret.stat().st_size < 32:
    raise SystemExit("adapter HMAC credential missing or too short")
if not str(secret).startswith("/run/credentials/") and secret.stat().st_mode & 0o077:
    raise SystemExit("adapter HMAC credential permissions are too broad")

database = Path(os.environ["CODESTRA_VICIDIAL_DB_FILE"])
if not database.is_file():
    raise SystemExit("database credential file missing")
if not str(database).startswith("/run/credentials/") and database.stat().st_mode & 0o077:
    raise SystemExit("database credential file missing or permissions too broad")
