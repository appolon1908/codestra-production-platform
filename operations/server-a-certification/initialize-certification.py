#!/usr/bin/env python3
"""Create a fail-closed Server A certification-input skeleton."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DB_PACKAGE = Path(__file__).resolve().parents[1] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import ContractError, atomic_write_json, load_json  # noqa: E402

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_CONTRACT = Path(__file__).resolve().with_name("certification-gates.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--installed-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        for field, value in (
            ("source commit", args.source_commit),
            ("installed commit", args.installed_commit),
        ):
            if not SHA_RE.fullmatch(value):
                raise ContractError(f"{field} must be an exact lowercase Git SHA")
        contract = load_json(args.contract)
        if contract.get("schema") != "codestra.server-a-certification-gates.v1":
            raise ContractError("unsupported certification gate contract")
        gates = {
            name: {"status": "FAIL", "evidence": []}
            for name in contract.get("required_pass", [])
        }
        for name, exception in (contract.get("required_warning") or {}).items():
            gates[name] = {
                "status": "WARNING",
                "exception": exception,
                "evidence": [],
            }
        payload = {
            "schema": "codestra.server-a-certification-input.v2",
            "target_server": contract["target_server"],
            "source_commit": args.source_commit,
            "installed_commit": args.installed_commit,
            "gates": gates,
        }
        atomic_write_json(args.output, payload)
        print(json.dumps({"status": "PASS", "output": str(args.output), "gate_count": len(gates)}))
        return 0
    except (ContractError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"CERTIFICATION_INITIALIZE=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
