#!/usr/bin/env python3
"""Fail closed unless the n8n queue runtime uses an immutable image."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^[a-z0-9./_-]+(?::[a-z0-9._-]+)?@sha256:[0-9a-f]{64}$")


def main() -> int:
    image = os.getenv("N8N_IMAGE", "")
    if not DIGEST.fullmatch(image):
        print("N8N_IMAGE_DIGEST_GATE=FAIL", file=sys.stderr)
        return 2
    compose = yaml.safe_load((ROOT / "deploy/n8n/compose.queue.yaml").read_text())
    services = compose.get("services", {})
    if set(services) != {"n8n-main", "n8n-webhook", "n8n-worker"}:
        print("N8N_QUEUE_TOPOLOGY_GATE=FAIL", file=sys.stderr)
        return 3
    common = compose["x-n8n-common"]["environment"]
    required = {
        "EXECUTIONS_MODE": "queue", "N8N_METRICS": "true",
        "N8N_METRICS_INCLUDE_QUEUE_METRICS": "true", "EXECUTIONS_DATA_PRUNE": "true",
    }
    if any(common.get(key) != value for key, value in required.items()):
        print("N8N_QUEUE_POLICY_GATE=FAIL", file=sys.stderr)
        return 4
    print("N8N_IMAGE_DIGEST_GATE=PASS")
    print("N8N_QUEUE_TOPOLOGY_GATE=PASS")
    print("N8N_QUEUE_POLICY_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
