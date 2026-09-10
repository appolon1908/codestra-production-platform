"""Publish recorded calling observations without inventing values or timestamps."""
from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from pathlib import Path

from .calling_readiness import FLAGS, MAX_BYTES, _read


def build_observed(readback):
    """Normalize explicit runtime flag observations, retaining unknowns as null."""
    if not isinstance(readback, dict) or readback.get("schema_version") != "calling-evidence.v1":
        raise ValueError("invalid calling observation schema")
    result = copy.deepcopy(readback)
    safety = result.get("safety")
    if not isinstance(safety, dict) or any(name not in safety for name in FLAGS):
        raise ValueError("incomplete runtime safety observations")
    if not isinstance(result.get("server_b"), dict):
        raise ValueError("missing Server B observations")
    for name in FLAGS:
        value = safety[name]
        if value is None or type(value) is bool:
            continue
        if isinstance(value, str) and value.strip().lower() in {"false", "disabled"}:
            safety[name] = False
        elif isinstance(value, str) and value.strip().lower() in {"true", "enabled"}:
            safety[name] = True
        else:
            raise ValueError("invalid runtime safety observation")
    # Preserve collection times, all release identities, counters, and proofs.
    # A normalized document can still be BLOCKED; publication is not certification.
    return result


def publish(readback_path, output_path):
    document = build_observed(_read(readback_path))
    payload = (json.dumps(document, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(payload) > MAX_BYTES:
        raise ValueError("oversized calling observations")
    output = Path(output_path)
    fd, temporary = tempfile.mkstemp(prefix=".calling-observed-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o640)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readback", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        publish(args.readback, args.output)
    except (OSError, ValueError, TypeError, RecursionError):
        print("CALLING_OBSERVATIONS=INVALID_OR_UNAVAILABLE")
        return 1
    print("CALLING_OBSERVATIONS=PUBLISHED; CERTIFICATION=NOT_EVALUATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
