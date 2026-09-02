#!/usr/bin/env python3
"""Fail-closed structural validation for the production persistence inventory."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import re
import sys

import yaml


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
    "redis-ephemeral-coordination",
}
REQUIRED_FIELDS = {
    "id", "service", "store", "kind", "source_authority", "database_owner",
    "application_role", "migration_framework", "backup_method", "restore_method",
    "target_rpo_hours", "target_rto_hours", "local_backup", "off_host_backup",
    "isolated_restore",
    "evidence_bundle",
}


def validate(path: Path, evidence_root: Path | None = None) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
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
