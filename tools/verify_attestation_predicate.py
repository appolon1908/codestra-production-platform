#!/usr/bin/env python3
"""Compare copied evidence with a payload already authenticated by Cosign.

This is a content-binding check, not a substitute for cryptographic signature,
certificate identity, statement type, or immutable image-subject verification.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
from pathlib import Path
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            # Do not echo untrusted evidence keys or values into CI logs.
            raise ValueError("attestation evidence contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("attestation evidence contains a non-finite JSON number")


def _loads(text: str | bytes) -> Any:
    return json.loads(
        text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def documents(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("attestation verification output is empty")
    try:
        parsed = _loads(text)
        values = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        try:
            values = [_loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ValueError("attestation verification output is malformed JSON") from exc
    if not values or any(not isinstance(value, dict) for value in values):
        raise ValueError("attestation verification documents must be JSON objects")
    return values


def _canonical_predicate(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        raise ValueError("attestation predicate must be a nonempty JSON object")
    # Python equality equates True with 1, including inside nested dictionaries.
    # Canonical JSON preserves those JSON types while ignoring object key order.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def statement(document: dict[str, Any]) -> dict[str, Any]:
    """Decode a verified envelope without accepting ambiguous JSON content."""
    payload = document.get("payload")
    if not isinstance(payload, str) or not payload:
        raise ValueError("verified attestation document has no payload")
    try:
        decoded = _loads(base64.b64decode(payload, validate=True))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("verified attestation payload is malformed") from exc
    if not isinstance(decoded, dict) or "predicate" not in decoded:
        raise ValueError("verified attestation statement has no predicate")
    _canonical_predicate(decoded["predicate"])
    return decoded


def validate(verification: Path, predicate: Path) -> None:
    try:
        expected = _canonical_predicate(_loads(predicate.read_text(encoding="utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("copied attestation predicate is malformed JSON") from exc
    matched = False
    for document in documents(verification):
        actual = _canonical_predicate(statement(document)["predicate"])
        if actual == expected:
            matched = True
    # Validate every envelope before accepting a match. A matching first record
    # must not hide a malformed or truncated trailing verification document.
    if not matched:
        raise ValueError("verified attestation predicate differs from copied evidence")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--predicate", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate(args.verification, args.predicate)
    except (OSError, ValueError) as exc:
        # Failure classes are sufficient; evidence contents can contain secrets.
        parser.exit(1, f"attestation predicate verification failed: {type(exc).__name__}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
