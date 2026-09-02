#!/usr/bin/env python3
"""Fail-closed structural validation for the production persistence inventory."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import re
import sys

REQUIRED_IDS = {
    "middleware-postgresql",
    "control-plane-postgresql",
    "email-postgresql",
    "odoo-postgresql-filestore",
    "n8n-postgresql-state",
    "keycloak-postgresql",
    "kong-postgresql-configuration",
    "openbao-raft",
    "caddy-configuration",
    "platform-release-authority",
    "reseller-portal-postgresql",
    "mail-registry-sqlite",
    "private-integration-gateway-state",
    "vicidial-adapter-state",
    "telephony-event-ledger",
    "kong-standby-auth-state",
    "prometheus-tsdb",
    "alertmanager-state",
    "stalwart-mail-state",
    "redis-ephemeral-coordination",
}


def scalar(value: str):
    value = value.strip()
    if value in {"null", "~"}:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def load_manifest(path: Path) -> dict:
    """Parse the intentionally restricted manifest subset without third-party code."""
    document: dict = {}
    section = "top"
    component = None
    component_indent = -1
    nested_key = None
    nested_indent = -1
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        if indent == 0 and text in {"policy:", "components:"}:
            section = text[:-1]
            if section == "components":
                document[section] = []
            else:
                document[section] = {}
            continue
        if indent == 0 and not text.startswith("- "):
            key, separator, value = text.partition(":")
            assert separator and re.fullmatch(r"[a-z_][a-z0-9_]*", key), "unsupported manifest syntax"
            document[key] = scalar(value)
            section = "top"
            continue
        if section == "components" and text.startswith("- "):
            component = {}
            document["components"].append(component)
            component_indent = indent
            nested_key = None
            text = text[2:]
        key, separator, value = text.partition(":")
        assert separator and re.fullmatch(r"[a-z_][a-z0-9_]*", key), "unsupported manifest syntax"
        if section == "top" and indent == 0:
            document[key] = scalar(value)
        elif section == "policy" and indent > 0:
            document["policy"][key] = scalar(value)
        elif section == "components" and component is not None:
            if nested_key is not None and indent > nested_indent:
                component[nested_key][key] = scalar(value)
            elif value.strip() == "" and indent > component_indent:
                component[key] = {}
                nested_key = key
                nested_indent = indent
            else:
                component[key] = scalar(value)
                nested_key = None
        else:
            raise AssertionError("unsupported manifest structure")
    return document
REQUIRED_FIELDS = {
    "id", "service", "store", "kind", "source_authority", "database_owner",
    "application_role", "migration_framework", "backup_method", "restore_method",
    "target_rpo_hours", "target_rto_hours", "local_backup", "off_host_backup",
    "isolated_restore",
    "evidence_bundle",
}


def validate(path: Path, evidence_root: Path | None = None) -> None:
    document = load_manifest(path)
    assert document["schema_version"] == "codestra.production-database-manifest.v1"
    assert document["target"] == "65.109.65.169"
    policy = document["policy"]
    assert policy == {
        "backup_over_production_restore_allowed": False,
        "normal_startup_migrations_allowed": False,
        "plaintext_off_host_backup_allowed": False,
        "certified_only_after_isolated_restore": True,
    }
    components = document["components"]
    ids = [component["id"] for component in components]
    assert len(ids) == len(set(ids)), "duplicate component id"
    assert set(ids) == REQUIRED_IDS, f"persistence coverage mismatch: {set(ids) ^ REQUIRED_IDS}"
    for component in components:
        assert REQUIRED_FIELDS <= component.keys(), f"incomplete component: {component.get('id')}"
        assert component["target_rpo_hours"] >= 0
        assert component["target_rto_hours"] > 0
        if component["kind"] != "redis":
            assert component["isolated_restore"] != "N/A"
            assert component["local_backup"] != "N/A"
            assert component["off_host_backup"] != "N/A"
        else:
            assert component["local_backup"] == "N/A"
            assert component["off_host_backup"] == "N/A"
        assert "certification_status" not in component, (
            "certification status belongs at manifest level"
        )
    if document["certification_status"] == "PASS":
        assert evidence_root is not None, "PASS requires an evidence root"
        for component in components:
            assert component["isolated_restore"] == "PASS"
            if component["kind"] != "redis":
                assert component["local_backup"] == "PASS"
                assert component["off_host_backup"] == "PASS"
            evidence = component["evidence_bundle"]
            assert isinstance(evidence, dict)
            assert set(evidence) == {"path", "sha256", "captured_at"}
            assert re.fullmatch(r"[A-Za-z0-9._/-]+", evidence["path"])
            assert not evidence["path"].startswith("/")
            assert ".." not in Path(evidence["path"]).parts
            assert re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])
            captured = datetime.fromisoformat(evidence["captured_at"].replace("Z", "+00:00"))
            assert captured.tzinfo is not None
            assert captured <= datetime.now(timezone.utc)
            evidence_path = evidence_root / evidence["path"]
            assert evidence_path.is_file()
            assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == evidence["sha256"]


if __name__ == "__main__":
    manifest = Path(sys.argv[1] if len(sys.argv) > 1 else "PRODUCTION-DATABASE-MANIFEST.yaml")
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    validate(manifest, root)
    print("PRODUCTION_DATABASE_MANIFEST=PASS")
