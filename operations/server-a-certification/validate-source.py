#!/usr/bin/env python3
"""Validate the repository-side Server A controls without live host access."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "operations" / "server-a-certification"
DATABASE = ROOT / "operations" / "database-certification"
BANNED_GENERATED_CONTAINER_NAMES = {
    "codestra-platform-apps-keycloak-db-1",
    "codestra-postgres-1",
    "codestra-identity-identity-db-1",
}
FORBIDDEN_INSTALL_PATTERNS = [
    re.compile(r"systemctl\s+(?:restart|reload|try-restart)\s+(?:ssh|sshd)(?:\.service)?", re.I),
    re.compile(r"(?:cp|install|mv|rm|sed|perl|tee)[^\n]*(?:/etc/ssh|authorized_keys)", re.I),
    re.compile(r"(?:sshd_config|authorized_keys)[^\n]*(?:>|>>)", re.I),
]
REQUIRED_RECOVERY_APPLICATIONS = {
    "keycloak",
    "n8n",
    "control-plane",
    "appolon",
    "beyvra-email",
    "email-reseller",
}
REQUIRED_AUDITS = {
    "audit-container-policy.py": "container-policy.rules.yml",
    "audit-environment-isolation.py": "environment-isolation.rules.yml",
    "audit-database-security.py": "database-security.rules.yml",
    "audit-realtime-ha.py": "realtime-ha.rules.yml",
    "audit-odoo-copy-governance.py": "odoo-copy-governance.rules.yml",
    "audit-redis-recovery.py": "redis-recovery.rules.yml",
    "audit-runtime-source-lock.py": "runtime-source-lock.rules.yml",
}
REQUIRED_UNITS = {
    "codestra-database-security-audit.service",
    "codestra-database-security-audit.timer",
    "codestra-realtime-ha-audit.service",
    "codestra-realtime-ha-audit.timer",
    "codestra-odoo-copy-governance-audit.service",
    "codestra-odoo-copy-governance-audit.timer",
    "codestra-redis-recovery-audit.service",
    "codestra-redis-recovery-audit.timer",
    "codestra-runtime-source-lock-audit.service",
    "codestra-runtime-source-lock-audit.timer",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_source_contracts() -> None:
    json_files = {
        *DATABASE.rglob("*.json"),
        *DATABASE.rglob("*.json.example"),
        *PACKAGE.rglob("*.json"),
        *PACKAGE.rglob("*.json.example"),
    }
    for path in sorted(json_files):
        load_json(path)
    yaml_files = {
        *DATABASE.rglob("*.yml"),
        *DATABASE.rglob("*.yaml"),
        *PACKAGE.rglob("*.yml"),
        *PACKAGE.rglob("*.yaml"),
    }
    for path in sorted(yaml_files):
        list(yaml.safe_load_all(path.read_text(encoding="utf-8")))


def main() -> int:
    python_sources = sorted(DATABASE.rglob("*.py")) + sorted(PACKAGE.rglob("*.py"))
    assert_true(bool(python_sources), "repository control package has no Python sources")
    for path in python_sources:
        compile(path.read_text(encoding="utf-8"), str(path), "exec", dont_inherit=True)
    parse_source_contracts()

    targets = load_json(DATABASE / "database-targets.json")
    assert_true(targets["schema"] == "codestra.database-backup-targets.v2", "backup target schema changed")
    assert_true(targets["environment"] == "production", "database target environment must be production")
    database_ids: list[str] = []
    applications: set[str] = set()
    for instance in targets["postgres_instances"]:
        assert_true(
            "compose_project" in instance and "compose_service" in instance,
            "stable Compose labels are required",
        )
        assert_true("container_name" not in instance, "generated container names are forbidden")
        for database in instance["databases"]:
            database_ids.append(database["id"])
            if database.get("application"):
                applications.add(database["application"])
    assert_true("keycloak" in database_ids, "Keycloak backup target is mandatory")
    assert_true(len(database_ids) == len(set(database_ids)), "database ids must be unique")
    assert_true(
        REQUIRED_RECOVERY_APPLICATIONS <= applications,
        f"selective recovery applications missing: {sorted(REQUIRED_RECOVERY_APPLICATIONS - applications)}",
    )
    assert_true(bool(targets.get("volume_archives")), "filestore/volume recovery targets are mandatory")
    assert_true(bool(targets.get("sqlite_targets")), "SQLite recovery targets are mandatory")

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in [DATABASE / "backup-all-databases.py", DATABASE / "database-targets.json"]
    )
    for banned in BANNED_GENERATED_CONTAINER_NAMES:
        assert_true(
            banned not in combined,
            f"hard-coded generated container name is forbidden: {banned}",
        )
    runtime = (DATABASE / "runtime_contract.py").read_text(encoding="utf-8")
    assert_true("com.docker.compose.project" in runtime, "project label resolver is required")
    assert_true("com.docker.compose.service" in runtime, "service label resolver is required")
    backup = (DATABASE / "backup-all-databases.py").read_text(encoding="utf-8")
    restore = (DATABASE / "restore-all-databases.py").read_text(encoding="utf-8")
    for required in (
        "CODESTRA_DATABASE_BACKUP_GPG_SIGNING_KEY",
        "validate_immutability_evidence",
        "synchronize_remote_status",
        "off_host_copy",
    ):
        assert_true(required in backup, f"backup contract is missing {required}")
    for required in (
        "OFF_HOST_ENCRYPTED_COPY",
        "VALIDSIG",
        "prove_n8n_credential_recovery",
        "keycloak_restored_startup",
        "safe_extract_tar",
    ):
        assert_true(required in restore, f"restore contract is missing {required}")

    mission = yaml.safe_load((PACKAGE / "mission.yaml").read_text(encoding="utf-8"))
    assert_true(mission["execution"]["repository_first"] is True, "repository-first is mandatory")
    assert_true(
        mission["safety"]["ssh_configuration_changes"] == "prohibited",
        "SSH mutation must remain prohibited",
    )
    assert_true(
        mission["safety"]["production_business_writes"] == "prohibited",
        "business writes must remain prohibited",
    )

    for name in ("install.sh", "activate.sh", "rollback.sh"):
        source = (PACKAGE / name).read_text(encoding="utf-8")
        for pattern in FORBIDDEN_INSTALL_PATTERNS:
            assert_true(
                pattern.search(source) is None,
                f"{name} contains a forbidden SSH mutation pattern",
            )
    activation = (PACKAGE / "activate.sh").read_text(encoding="utf-8")
    for required in (
        "codestra-database-security-audit.service",
        "codestra-realtime-ha-audit.service",
        "codestra-odoo-copy-governance-audit.service",
        "codestra-redis-recovery-audit.service",
        "codestra-runtime-source-lock-audit.service",
        "centrifugo_consecutive_successes':10",
        "governance_consecutive_successes':3",
        "rollback_activation",
    ):
        assert_true(required in activation, f"activation contract is missing {required}")

    firewall = (PACKAGE / "firewall" / "server-a-firewall.py").read_text(encoding="utf-8")
    assert_true("CODESTRA_OUT_OF_BAND_CONSOLE_CONFIRMED" in firewall, "firewall apply must require console proof")
    assert_true("systemd-run" in firewall, "firewall apply must arm an automatic rollback")
    assert_true("ssh_state()" in firewall, "firewall transaction must compare SSH state")
    assert_true("policy drop" in firewall, "firewall candidate must be default deny")
    assert_true("ct original proto-dst" in firewall, "Docker filtering must use the original published port")
    assert_true("default deny other public forwarding" in firewall, "public forwarding must fail closed")

    governance = (PACKAGE / "publish-governance-status.py").read_text(encoding="utf-8")
    assert_true("/statuses/" in governance, "governance publisher must use commit statuses")
    assert_true("statuses?per_page=100" in governance, "governance publisher must read back status")
    assert_true("CODESTRA_GOVERNANCE_TOKEN_FILE" in governance, "governance token must come from a protected file")

    centrifugo = load_json(PACKAGE / "centrifugo-probe.json.example")
    probe_ids = {item["id"] for item in centrifugo["http_probes"]}
    assert_true(probe_ids == {"internal", "external"}, "Centrifugo internal and external probes are mandatory")
    assert_true(
        centrifugo["websocket_probe"]["url"].startswith("REPLACE_"),
        "Centrifugo path must not be guessed in source",
    )

    for script, rule in REQUIRED_AUDITS.items():
        assert_true((PACKAGE / script).is_file(), f"required audit is missing: {script}")
        assert_true((PACKAGE / rule).is_file(), f"required alert rules are missing: {rule}")
    unit_names = {path.name for path in (PACKAGE / "systemd").iterdir() if path.is_file()}
    assert_true(REQUIRED_UNITS <= unit_names, f"required units missing: {sorted(REQUIRED_UNITS - unit_names)}")

    gates = load_json(PACKAGE / "certification-gates.json")
    mandatory = set(gates["required_pass"])
    for expected in {
        "central_backup",
        "restore_from_offhost",
        "keycloak_restored_startup",
        "n8n_credential_recovery",
        "centrifugo_internal_probe",
        "financial_governance_publisher",
        "host_ipv4_input_default_drop",
        "ssh_config_unchanged",
        "normal_application_superusers_zero",
        "database_connect_isolation",
        "realtime_replication_health",
        "false_realtime_standby_removed",
        "odoo_copy_governance",
        "odoo_filestore_alignment",
        "redis_recovery_matrix",
        "production_business_writes_zero",
    }:
        assert_true(expected in mandatory, f"mandatory certification gate missing: {expected}")
    assert_true(
        gates["required_warning"]["ssh_security_posture"] == "OWNER_ACCEPTED_NO_CHANGE",
        "SSH warning contract changed",
    )

    unit_files = list((DATABASE / "systemd").iterdir()) + list((PACKAGE / "systemd").iterdir())
    for path in unit_files:
        source = path.read_text(encoding="utf-8")
        assert_true(
            "/opt/codestra/production-controls/current/" in source or path.suffix == ".timer",
            f"unit is not release-symlink based: {path.name}",
        )
        assert_true(
            "ssh.service" not in source and "sshd.service" not in source,
            f"unit touches SSH: {path.name}",
        )

    print("SERVER_A_REPOSITORY_CONTROLS=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"SERVER_A_REPOSITORY_CONTROLS=FAIL:{exc}", file=sys.stderr)
        raise SystemExit(1)
