#!/usr/bin/env python3
"""Upgrade governed workflows to the complete template and leave them inactive."""
from __future__ import annotations

import copy
import json
import sys


if len(sys.argv) != 4:
    raise SystemExit("usage: migrate_n8n_stateless.py CURRENT GENERATED OUTPUT")

with open(sys.argv[1], encoding="utf-8") as handle:
    current = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    generated = json.load(handle)

templates = {item["id"]: item for item in generated}
changed = 0
for workflow in current:
    template = templates.get(workflow.get("id"))
    if not template:
        continue
    for key in ("name", "nodes", "connections", "settings", "tags", "meta"):
        workflow[key] = copy.deepcopy(template[key])
    # The upgraded graph now executes governed business-process calls. Migration
    # must never preserve an old active bit across that trust-boundary change.
    workflow["active"] = False
    workflow["staticData"] = None
    changed += 1

if changed != len(templates):
    raise SystemExit(f"expected {len(templates)} governed workflows, changed {changed}")

with open(sys.argv[3], "w", encoding="utf-8") as handle:
    json.dump(current, handle, indent=2)
print(f"changed={changed} active_after_migration={sum(bool(x.get('active')) for x in current if x.get('id') in templates)}")
