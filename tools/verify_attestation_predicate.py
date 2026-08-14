#!/usr/bin/env python3
"""Prove a copied predicate equals a live Cosign verification payload."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path


def documents(path: Path) -> list[dict]:
    text = path.read_text().strip()
    if not text:
        raise ValueError("attestation verification output is empty")
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def validate(verification: Path, predicate: Path) -> None:
    expected = json.loads(predicate.read_text())
    for document in documents(verification):
        payload = document.get("payload")
        if not isinstance(payload, str):
            continue
        statement = json.loads(base64.b64decode(payload, validate=True))
        if statement.get("predicate") == expected:
            return
    raise ValueError("verified attestation predicate differs from copied evidence")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--predicate", type=Path, required=True)
    args = parser.parse_args()
    validate(args.verification, args.predicate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
