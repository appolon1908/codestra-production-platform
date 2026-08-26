#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def docker_inspect(target: str) -> dict:
    raw = subprocess.check_output(["docker", "inspect", target], text=True)
    return json.loads(raw)[0]


parser = argparse.ArgumentParser()
parser.add_argument("--image", required=True)
parser.add_argument("--source", required=True)
parser.add_argument("--revision", required=True)
parser.add_argument("--container", default="codestra-odoo-1")
args = parser.parse_args()

if "@sha256:" not in args.image:
    raise SystemExit("ODOO_IMAGE_NOT_IMMUTABLE")

contract = json.loads((ROOT / "config/odoo-production-contract.json").read_text())
expected_routes = {
    (method, route["path"])
    for route in contract["private_integration"]["routes"]
    for method in route["methods"]
}
if expected_routes != {
    ("POST", "/api/v1/integration/results"),
    ("POST", "/codestra/api/v1/call-events"),
    ("GET", "/web/health"),
    ("HEAD", "/web/health"),
}:
    raise SystemExit("ODOO_PRIVATE_ALLOWLIST_DRIFT")

image = docker_inspect(args.image)
labels = image["Config"].get("Labels") or {}
if labels.get("org.opencontainers.image.source") != args.source:
    raise SystemExit("ODOO_OCI_SOURCE_MISMATCH")
if labels.get("org.opencontainers.image.revision") != args.revision:
    raise SystemExit("ODOO_OCI_REVISION_MISMATCH")

container = docker_inspect(args.container)
published = container["HostConfig"].get("PortBindings") or {}
if any(bindings for bindings in published.values()):
    raise SystemExit("ODOO_PUBLIC_PORT_EXPOSURE")

subprocess.run([str(ROOT / "scripts/test_odoo_private_allowlist.sh")], check=True)
print("ODOO_DEPLOYMENT_PREFLIGHT=PASS")
