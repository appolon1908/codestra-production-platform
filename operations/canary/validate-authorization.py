#!/usr/bin/env python3
"""Fail-closed, sanitized validation for a signed one-call authorization."""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MANDATORY = (
    "SIGNED_CANARY_APPROVAL",
    "CANARY_APPROVAL_DOCUMENT_REFERENCE",
    "CANARY_SIGNATURE_REFERENCE",
    "CANARY_APPROVER",
    "CANARY_APPROVER_AUTHORITY_REFERENCE",
    "CANARY_CHANGE_ID",
    "CANARY_START",
    "CANARY_END",
    "CANARY_TIMEZONE",
    "MAX_CALLS",
    "MAX_CONCURRENT_CALLS",
    "MAX_CALL_DURATION_SECONDS",
    "MAX_EVENTS",
    "RETRY_CALLS_AUTHORIZED",
    "TEST_CAMPAIGN",
    "SYNTHETIC_LIST",
    "TEST_AGENT",
    "TEST_USER_GROUP",
    "TEST_TRUNK",
    "TEST_CARRIER_ROUTE",
    "AUTHORIZED_CALLER_ID",
    "CALLER_ID_APPROVAL_REFERENCE",
    "PROTECTED_DESTINATION_REFERENCE",
    "DESTINATION_OWNER",
    "DESTINATION_OWNER_CONFIRMATION",
    "ZERO_MATCH_APPROVAL",
    "ZERO_MATCH_APPROVAL_TIMESTAMP",
    "ZERO_MATCH_APPROVAL_EXPIRATION",
    "HUMAN_CANARY_OPERATOR",
    "OPERATOR_CONFIRMATION_REFERENCE",
    "RECORDING_AUTHORIZED",
    "RECORDING_POLICY_REFERENCE",
    "CALLBACK_AUTHORIZED",
    "ROLLBACK_OWNER",
    "EMERGENCY_DISABLE_OWNER",
)
INVALID = re.compile(
    r"(?:^|[_\s-])(TBD|TODO|UNKNOWN|PLACEHOLDER|BLOCKED|ABSENT|NONE|UNASSIGNED)(?:$|[_\s-])",
    re.I,
)
VALIDATION_STATES = {
    "VALIDATED",
    "INVALID",
    "INACCESSIBLE",
    "EXPIRED",
    "SCOPE_MISMATCH",
    "APPROVAL_MISSING",
    "NOT_PROVIDED",
}


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip("'\"")
    return values


def timestamp(value: str, timezone: ZoneInfo) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(dt.timezone.utc)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-authorization.py PROTECTED_AUTHORIZATION_ENV", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print("authorization_state=INACCESSIBLE reason=record_missing", file=sys.stderr)
        return 2
    values = parse(path)
    missing = [key for key in MANDATORY if not values.get(key)]
    invalid = [key for key in MANDATORY if values.get(key) and INVALID.search(values[key])]
    if missing or invalid:
        names = ",".join(sorted(set(missing + invalid)))
        print(f"authorization_state=NOT_PROVIDED invalid_keys={names}", file=sys.stderr)
        return 2
    if values["SIGNED_CANARY_APPROVAL"] not in VALIDATION_STATES:
        print("authorization_state=INVALID reason=invalid_validation_state", file=sys.stderr)
        return 2
    if values["SIGNED_CANARY_APPROVAL"] != "VALIDATED":
        print(f"authorization_state={values['SIGNED_CANARY_APPROVAL']} reason=signature_not_validated", file=sys.stderr)
        return 2
    exact = {
        "CANARY_TIMEZONE": "America/Santo_Domingo",
        "MAX_CALLS": "1",
        "MAX_CONCURRENT_CALLS": "1",
        "RETRY_CALLS_AUTHORIZED": "NO",
    }
    mismatched = [key for key, required in exact.items() if values[key] != required]
    if mismatched:
        print(f"authorization_state=SCOPE_MISMATCH invalid_keys={','.join(mismatched)}", file=sys.stderr)
        return 2
    try:
        maximum_duration = int(values["MAX_CALL_DURATION_SECONDS"])
        maximum_events = int(values["MAX_EVENTS"])
        timezone = ZoneInfo(values["CANARY_TIMEZONE"])
        start = timestamp(values["CANARY_START"], timezone)
        end = timestamp(values["CANARY_END"], timezone)
        zero_match_expiration = timestamp(values["ZERO_MATCH_APPROVAL_EXPIRATION"], timezone)
    except (ValueError, ZoneInfoNotFoundError):
        print("authorization_state=INVALID reason=invalid_time_or_limit", file=sys.stderr)
        return 2
    if maximum_duration <= 0 or maximum_events <= 0 or start >= end:
        print("authorization_state=SCOPE_MISMATCH reason=invalid_bounds", file=sys.stderr)
        return 2
    now = dt.datetime.now(dt.timezone.utc)
    if now < start:
        print("authorization_state=INVALID reason=window_not_started", file=sys.stderr)
        return 2
    if now > end or now > zero_match_expiration:
        print("authorization_state=EXPIRED reason=window_or_zero_match_expired", file=sys.stderr)
        return 2
    print(
        "authorization_state=VALIDATED "
        f"change_reference_present=true window_seconds={int((end - start).total_seconds())} "
        f"max_calls=1 max_concurrent_calls=1 max_duration_seconds={maximum_duration} "
        f"max_events={maximum_events} retry_calls_authorized=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
