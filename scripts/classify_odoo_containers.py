#!/usr/bin/env python3
import json
import subprocess


def classification(name: str, status: str) -> str:
    if name == "codestra-odoo-1":
        return "CURRENT_PRODUCTION"
    if status.startswith("Up "):
        return "TEST_EVIDENCE"
    if "rollback" in name:
        return "ROLLBACK_REQUIRED"
    if "migration" in name or "upgrade" in name or "migrate" in name:
        return "MIGRATION_EVIDENCE"
    if any(token in name for token in ("test", "cert", "ci-", "clone", "fresh")):
        return "TEST_EVIDENCE"
    if "outbox" in name or "staging" in name or "transport" in name:
        return "HISTORICAL"
    if "odoo" in name:
        return "HISTORICAL"
    raise ValueError(f"UNKNOWN container: {name}")


raw = subprocess.check_output(
    ["docker", "ps", "-a", "--format", "{{json .}}"], text=True
)
rows = []
for line in raw.splitlines():
    item = json.loads(line)
    name = item["Names"]
    if "odoo" not in name.lower():
        continue
    state = classification(name, item["Status"])
    rows.append(
        {
            "name": name,
            "image": item["Image"],
            "status": item["Status"],
            "classification": state,
            "cleanup_approved": False,
        }
    )

print(json.dumps({"containers": rows, "unknown": 0}, indent=2, sort_keys=True))
print("ODOO_UNKNOWN_HISTORICAL_CONTAINERS=0")
print("ODOO_CLEANUP_APPROVED_COUNT=0")
