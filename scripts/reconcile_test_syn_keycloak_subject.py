#!/usr/bin/env python3
"""Reconcile the dedicated TEST_SYN user to its canonical Keycloak subject.

Dry-run is the default.  The supported Keycloak partial-import API is required
because the ordinary create-user endpoint intentionally generates a new UUID.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USERNAME = "synthetic.agent.test.syn.6101"
CANONICAL_SUBJECT = "46c6027f-1ea8-4010-a104-5b908aabb715"
STALE_SUBJECT = "ca9b1218-c2d0-43f0-9c16-15cc60d7b0f4"
REALM = "codestra"


class Keycloak:
    def __init__(self, base_url: str, config_path: Path):
        config = json.loads(config_path.read_text())
        endpoint = next(iter(config["endpoints"].values()))["master"]
        body = urlencode({
            "grant_type": "client_credentials",
            "client_id": endpoint["clientId"],
            "client_secret": endpoint["secret"],
        }).encode()
        response = self._open(
            f"{base_url}/realms/master/protocol/openid-connect/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
        )
        self.base_url = base_url.rstrip("/")
        self.token = response["access_token"]

    @staticmethod
    def _open(url: str, *, method: str = "POST", data: bytes | None = None,
              content_type: str = "application/json", token: str | None = None):
        headers = {"Content-Type": content_type}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urlopen(Request(url, method=method, data=data, headers=headers), timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def call(self, path: str, method: str = "GET", payload=None):
        return self._open(
            self.base_url + path,
            method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            token=self.token,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-config", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    kc = Keycloak(args.base_url, args.admin_config)

    users = kc.call(f"/admin/realms/{REALM}/users?username={USERNAME}&exact=true")
    canonical = [user for user in users if user["id"] == CANONICAL_SUBJECT]
    stale = kc.call(f"/admin/realms/{REALM}/users/{STALE_SUBJECT}") if not canonical else None
    result = {
        "username": USERNAME,
        "canonical_subject": CANONICAL_SUBJECT,
        "stale_subject": STALE_SUBJECT,
        "apply_requested": args.apply,
        "before_subjects": [user["id"] for user in users],
    }
    if canonical:
        result.update(status="PASS", changed=False, active_stale_subject_mappings=0)
    elif not stale or stale.get("username") != USERNAME:
        raise RuntimeError("canonical user absent and exact stale TEST_SYN authority not found")
    else:
        credentials = kc.call(f"/admin/realms/{REALM}/users/{STALE_SUBJECT}/credentials")
        if credentials:
            raise RuntimeError("refusing subject replacement because user has credentials")
        groups = kc.call(f"/admin/realms/{REALM}/users/{STALE_SUBJECT}/groups")
        roles = kc.call(f"/admin/realms/{REALM}/users/{STALE_SUBJECT}/role-mappings/realm")
        result.update(status="DRIFT", changed=False, credential_count=0,
                      group_paths=[group["path"] for group in groups],
                      realm_roles=[role["name"] for role in roles])
        if args.apply:
            representation = {key: stale[key] for key in (
                "firstName", "lastName", "email", "emailVerified", "attributes",
                "requiredActions",
            ) if key in stale}
            representation.update(id=CANONICAL_SUBJECT, username=USERNAME, enabled=True)
            kc.call(f"/admin/realms/{REALM}/users/{STALE_SUBJECT}", "DELETE")
            imported = kc.call(f"/admin/realms/{REALM}/partialImport", "POST", {
                "ifResourceExists": "FAIL", "users": [representation],
            })
            if imported.get("added") != 1:
                raise RuntimeError("canonical partial import did not add exactly one user")
            for group in groups:
                kc.call(f"/admin/realms/{REALM}/users/{CANONICAL_SUBJECT}/groups/{group['id']}", "PUT")
            if roles:
                kc.call(f"/admin/realms/{REALM}/users/{CANONICAL_SUBJECT}/role-mappings/realm", "POST", roles)
            after = kc.call(f"/admin/realms/{REALM}/users?username={USERNAME}&exact=true")
            if len(after) != 1 or after[0]["id"] != CANONICAL_SUBJECT or not after[0]["enabled"]:
                raise RuntimeError("canonical subject readback failed")
            result.update(status="PASS", changed=True,
                          after_subjects=[after[0]["id"]], active_stale_subject_mappings=0)

    args.evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"TEST_SYN_KEYCLOAK_RECONCILIATION={result['status']}")
    return 0 if result["status"] == "PASS" or not args.apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
