#!/usr/bin/env python3
"""Fail-closed structural validation for the production persistence inventory."""

from pathlib import Path
import sys

import yaml


REQUIRED_IDS = {
    "middleware-postgresql",
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
}


def validate(path: Path) -> None:
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
        assert "certification_status" not in component, (
            "certification status belongs at manifest level"
        )
    if document["certification_status"] == "PASS":
        for component in components:
            assert component["isolated_restore"] == "PASS"
            if component["off_host_backup"] != "N/A":
                assert component["off_host_backup"] == "PASS"


if __name__ == "__main__":
    validate(Path(sys.argv[1] if len(sys.argv) > 1 else "PRODUCTION-DATABASE-MANIFEST.yaml"))
    print("PRODUCTION_DATABASE_MANIFEST=PASS")
