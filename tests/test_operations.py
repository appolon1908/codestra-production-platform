from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "operations" / "backup"
MONITORING = ROOT / "operations" / "monitoring"


def load_receiver_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_receiver_files", MONITORING / "validate-receiver-files.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BACKUP / script)],
        cwd=ROOT,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )


class BackupOperationsTests(unittest.TestCase):
    def test_restore_rehearsal_preserves_isolated_owner_roles(self) -> None:
        source = (
            ROOT
            / "operations"
            / "readiness"
            / "codestra-isolated-restore-rehearsal.sh"
        ).read_text()
        self.assertIn("CREATE ROLE middleware_data_owner;", source)
        self.assertIn("grep -qx 'mw_integration_api|true|false|false|false'", source)
        self.assertIn(
            "CREATE ROLE mw_integration_api LOGIN NOINHERIT PASSWORD :'rehearsal_password';",
            source,
        )
        self.assertIn("CREATE ROLE keycloak_data_owner;", source)
        self.assertNotIn("GRANT middleware_data_owner TO middleware_app;", source)
        self.assertNotIn("GRANT keycloak_data_owner TO keycloak;", source)
        self.assertIn("-O middleware_app codestra_middleware", source)
        self.assertIn("-O keycloak_data_owner keycloak", source)
        self.assertIn("PRODUCTION-MIDDLEWARE-ROLE-BASELINE.txt", source)
        self.assertIn("PRODUCTION-KEYCLOAK-ROLE-AFTER.txt", source)
        self.assertIn("--exit-on-error", source)
        self.assertNotIn("--no-owner", source)
        self.assertIn("KEYCLOAK_DATA_OWNER_NOLOGIN=PASS", source)
        self.assertIn("RESTORE_ROLE_MEMBERSHIP_SCOPE=ISOLATED_ONLY", source)
        self.assertIn("PRODUCTION_ROLE_PRIVILEGES_UNCHANGED=PASS", source)
        self.assertIn("PUBLISHED_PORT_COUNT=0", source)

    def test_readiness_backup_publishes_last_success_after_evidence_validation(self) -> None:
        source = (ROOT / "operations" / "readiness" / "codestra-local-consistency-backup.sh").read_text()
        evidence = source.index('sha256sum -c EVIDENCE-SHA256SUMS')
        marker = source.index('mv "$backup_root/.LAST_SUCCESS-${stamp}" "$backup_root/LAST_SUCCESS"')
        self.assertGreater(marker, evidence)

    def test_restore_rehearsal_recreates_rbac_owners_before_exact_restore(self) -> None:
        backup = (ROOT / "operations" / "readiness" / "codestra-local-consistency-backup.sh").read_text()
        source = (ROOT / "operations" / "readiness" / "codestra-isolated-restore-rehearsal.sh").read_text()
        role = source.index("CREATE ROLE keycloak_data_owner;")
        restore = source.index('restore_args=(--exit-on-error)')
        self.assertLess(role, restore)
        self.assertIn("CREATE ROLE middleware_data_owner;", source)
        self.assertNotIn("GRANT middleware_data_owner TO middleware_app", source)
        self.assertIn("pg_has_role('middleware_app','middleware_data_owner','MEMBER')", source)
        self.assertIn("trap 'exit 130' INT", source)
        self.assertIn("trap 'exit 143' TERM", source)
        self.assertIn('expected-keycloak-owners.txt', backup)
        self.assertIn('expected-default-acl.txt', backup)
        self.assertNotIn('> "$work_dir/expected-keycloak-owners.txt"', source)
        self.assertIn("OBJECT_OWNERSHIP=PASS", source)
        self.assertIn("DEFAULT_PRIVILEGES_RESTORED=PASS", source)
        self.assertIn("PRODUCTION_ROLE_PRIVILEGES_UNCHANGED=PASS", source)

    def test_restore_rehearsal_uses_advertised_backup_and_publishes_bound_result(self) -> None:
        source = (
            ROOT
            / "operations"
            / "readiness"
            / "codestra-isolated-restore-rehearsal.sh"
        ).read_text()
        self.assertIn('backup_stamp=$(python3 - "$backup_root/LAST_SUCCESS"', source)
        self.assertIn('backup_dir="${backup_root}/${backup_stamp}"', source)
        self.assertNotIn("find \"$backup_root\" -mindepth 2", source)
        self.assertIn("RESTORE_BACKUP_STAMP=${backup_stamp}", source)
        checksum = source.index("sha256sum RESTORE-RESULT.txt")
        marker = source.index(
            'mv "$evidence_root/.LAST_SUCCESS-${stamp}" "$evidence_root/LAST_SUCCESS"'
        )
        self.assertGreater(marker, checksum)
        self.assertIn('sync -d "$evidence_root"', source)

    def test_restore_rehearsal_migrates_exact_candidate_on_internal_network(self) -> None:
        source = (
            ROOT
            / "operations"
            / "readiness"
            / "codestra-isolated-restore-rehearsal.sh"
        ).read_text()
        self.assertIn(
            "middleware_source_sha=63b6c0c8bca5168a1178895bd12858d0b1e8086e",
            source,
        )
        self.assertIn(
            "middleware_repository=ghcr.io/appolon1908-hue/codestra-middleware",
            source,
        )
        self.assertIn("middleware_required_head=0056_klyrow_delivery_events", source)
        self.assertIn('middleware_image="${middleware_repository}@${release_values[0]}"', source)
        self.assertIn('"${middleware_container_args[@]}"', source)
        self.assertIn("command.upgrade(c,'head')", source)
        self.assertIn("command.current(c)", source)
        self.assertIn("c.set_main_option('script_location','/app/migrations')", source)
        self.assertIn('"$middleware_image" -m app.entrypoints.integration_api', source)
        self.assertIn('"$middleware_image" -c', source)
        self.assertIn("MIDDLEWARE_ISOLATED_MIGRATION_GATE=PASS", source)
        self.assertIn("MIDDLEWARE_SCHEMA_TABLE_COUNT=${middleware_schema_table_count}", source)
        self.assertIn(
            "postgresql+asyncpg://mw_integration_api:%s@postgres:5432/codestra_middleware",
            source,
        )
        self.assertIn(
            "postgresql+asyncpg://middleware_app:%s@postgres:5432/codestra_middleware",
            source,
        )
        self.assertIn("MIDDLEWARE_MIGRATION_IDENTITY=middleware_app", source)
        self.assertIn("MIDDLEWARE_PRODUCTION_GRANTS_MATCH=PASS", source)
        self.assertIn('"$middleware_image" -m app.entrypoints.integration_api', source)
        self.assertIn('urlopen("http://middleware-candidate:8095/healthz"', source)
        self.assertIn('urlopen("http://middleware-candidate:8095/readyz"', source)
        self.assertIn("MIDDLEWARE_CANDIDATE_DATABASE_READINESS=PASS", source)
        self.assertIn('docker network create --internal', source)
        self.assertNotIn("--publish", source)
        self.assertNotIn("--publish-all", source)

    def test_readiness_backup_validates_exact_root_owned_owner_waiver(self) -> None:
        source = (ROOT / "operations" / "readiness" / "codestra-local-consistency-backup.sh").read_text()
        self.assertIn("os.O_NOFOLLOW", source)
        self.assertIn("os.fstat(stream.fileno())", source)
        self.assertIn("info.st_uid != 0 or info.st_gid != 0", source)
        self.assertIn("stat.S_IMODE(info.st_mode) != 0o600", source)
        self.assertIn("hashlib.sha256(waiver).hexdigest()", source)
        self.assertIn("if ! validate_owner_window_waiver; then", source)

    def test_backup_fails_closed_without_protected_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run(
                "codestra-backup.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_GPG_RECIPIENT": "",
                    "CODESTRA_BACKUP_REMOTE_HOST": "",
                },
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("required protected configuration missing", result.stderr)

    def test_freshness_check_passes_for_current_success_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "LAST_SUCCESS"
            marker.write_text(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "\n")
            result = run(
                "check-backup-state.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_MAX_AGE_SECONDS": "120",
                    "CODESTRA_BACKUP_MIN_FREE_BYTES": "1",
                },
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backup_age_seconds", result.stdout)

    def test_cleanup_never_deletes_and_preserves_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stamp in ("20260101T000000Z", "20260201T000000Z"):
                backup = root / stamp
                backup.mkdir()
                artifact = backup / "bundle.gpg"
                artifact.write_bytes(stamp.encode())
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                (backup / "SHA256SUMS").write_text(f"{digest}  bundle.gpg\n")
            result = run(
                "cleanup-backups.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_RETENTION_DAYS": "0",
                    "CODESTRA_BACKUP_MIN_VALID": "2",
                },
            )
            remaining = sorted(path.name for path in root.iterdir())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(remaining, ["20260101T000000Z", "20260201T000000Z"])
        self.assertIn("cleanup_mode=report_only", result.stdout)

    def test_cleanup_refuses_when_verified_minimum_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run(
                "cleanup-backups.sh",
                {
                    "CODESTRA_BACKUP_ROOT": directory,
                    "CODESTRA_BACKUP_MIN_VALID": "2",
                },
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing cleanup", result.stderr)


class MonitoringGovernanceTests(unittest.TestCase):
    def test_monitoring_installer_does_not_repeat_promtool_argv_zero(self) -> None:
        source = (MONITORING / "install-monitoring.sh").read_text()
        self.assertIn("--entrypoint /bin/promtool", source)
        self.assertIn("check config /etc/prometheus/prometheus.yml", source)
        self.assertNotIn("promtool check config", source)

    def test_platform_ci_publishes_required_legacy_status(self) -> None:
        workflow = (ROOT / ".github/workflows/platform-source-gate.yml").read_text()
        self.assertIn("statuses: write", workflow)
        self.assertIn("TARGET_SHA: ${{ github.event.pull_request.head.sha }}", workflow)
        self.assertIn('statuses/${TARGET_SHA}', workflow)
        self.assertIn("-f context=validate", workflow)
        self.assertIn("if: always()", workflow)

    def test_middleware_database_exporters_are_wired(self) -> None:
        compose = yaml.safe_load((MONITORING / "compose.monitoring.yaml").read_text())
        services = compose["services"]
        postgres = services["postgres-exporter"]
        self.assertIn("backend", postgres["networks"])
        self.assertEqual(
            postgres["environment"]["DATA_SOURCE_URI"],
            "codestra-postgres-1:5432/postgres?sslmode=disable",
        )
        self.assertEqual(postgres["environment"]["DATA_SOURCE_USER"], "codestra_monitoring")
        self.assertEqual(
            postgres["secrets"],
            [{"source": "postgres_monitoring_credential", "target": "postgres_monitoring_password"}],
        )
        node = services["node-exporter"]
        self.assertIn(
            "--collector.textfile.directory=/host/var/lib/node_exporter/textfile_collector",
            node["command"],
        )
        self.assertEqual(
            compose["secrets"]["postgres_monitoring_credential"]["file"],
            "/etc/codestra/secrets/monitoring-runtime/postgres_exporter_password",
        )
        prometheus = yaml.safe_load((MONITORING / "prometheus.yml").read_text())
        jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
        self.assertEqual(
            jobs["postgres-exporter"]["static_configs"][0]["targets"],
            ["postgres-exporter:9187"],
        )
        staging = jobs["operations-dashboard-middleware-staging"]
        self.assertEqual(
            staging["static_configs"][0]["targets"],
            ["middleware-intake-staging:8080"],
        )
        self.assertEqual(
            staging["oauth2"]["token_url"],
            "https://auth-staging.codestra.co/realms/codestra/protocol/openid-connect/token",
        )
        self.assertIn("operations_dashboard_staging", compose["services"]["prometheus"]["networks"])
        self.assertIn(
            "/etc/codestra/secrets/monitoring-runtime/staging_metrics_client_secret:/run/secrets/staging_metrics_client_secret:ro",
            compose["services"]["prometheus"]["volumes"],
        )
        projection = (MONITORING / "sync-staging-metrics-secret.sh").read_text()
        self.assertIn("/opt/codestra/secrets/identity-staging/monitoring-readonly-client-secret", projection)
        self.assertIn("install -o root -g 65534 -m 0640", projection)
        self.assertIn('cmp -s "$source_file" "$temporary"', projection)
        installer = (MONITORING / "install-monitoring.sh").read_text()
        self.assertIn('bash "$ROOT/sync-staging-metrics-secret.sh"', installer)
        self.assertIn('[[ -s "$staging_metrics_secret" && -r "$staging_metrics_secret" ]]', installer)
        self.assertEqual(
            compose["networks"]["operations_dashboard_staging"],
            {
                "external": True,
                "name": "codestra-operations-dashboard-staging_private",
            },
        )

    def test_middleware_database_recovery_metrics_are_fail_closed(self) -> None:
        source = (MONITORING / "exporters" / "recovery_metrics.sh").read_text()
        self.assertIn("OFFSERVER_COPY=PASS", source)
        self.assertIn("codestra_middleware_backup_last_success_timestamp_seconds", source)
        self.assertIn("codestra_systemd_timer_failed", source)
        self.assertIn("codestra_backup_replication_failures_total", source)
        self.assertIn("systemctl is-failed --quiet codestra-scraper-middleware-backup.service", source)
        self.assertIn("codestra_middleware_database_migration_match", source)
        self.assertIn("codestra-middleware-integration-api-1 alembic heads", source)
        self.assertIn("codestra-middleware-integration-api-1 alembic current", source)

    def test_receiver_validator_rejects_empty_invalid_and_placeholder_urls(self) -> None:
        config = MONITORING / "alertmanager.example.yml"
        names = ("primary_receiver_url", "secondary_receiver_url", "recovery_receiver_url", "rejected_route_url")
        for invalid in ("", "https://receiver.invalid/hook", "REPLACE_WITH_APPROVED"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in names:
                    (root / name).write_text(invalid)
                result = load_receiver_validator().validate(
                    config, root, expected_uid=os.getuid(), expected_gid=os.getgid()
                )
                self.assertEqual(result, 2)

    def test_receiver_validator_accepts_nonplaceholder_protected_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, name in enumerate(("primary_receiver_url", "secondary_receiver_url", "recovery_receiver_url", "rejected_route_url")):
                path = root / name
                path.write_text(f"https://alerts.internal.testdomain/receiver-{index}")
                path.chmod(0o600)
            result = load_receiver_validator().validate(
                MONITORING / "alertmanager.example.yml",
                root,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
            )
        self.assertEqual(result, 0)

    def test_receiver_validator_rejects_unsafe_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, name in enumerate(("primary_receiver_url", "secondary_receiver_url", "recovery_receiver_url", "rejected_route_url")):
                path = root / name
                path.write_text(f"https://alerts.internal.testdomain/receiver-{index}")
                path.chmod(0o666)
            result = load_receiver_validator().validate(
                MONITORING / "alertmanager.example.yml",
                root,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
            )
        self.assertEqual(result, 2)

    def test_empty_governance_template_fails_closed(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(MONITORING / "validate-governance.py"),
                str(MONITORING / "governance.env.example"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("PRODUCTION_ALERT_RECEIVER", result.stderr)
        self.assertIn("FINAL_CHANGE_ID", result.stderr)

    def test_complete_governance_references_validate(self) -> None:
        keys = (
            "PRODUCTION_ALERT_RECEIVER",
            "PRIMARY_ESCALATION_OWNER",
            "PRIMARY_ESCALATION_CONTACT_REFERENCE",
            "SECONDARY_ESCALATION_OWNER",
            "SECONDARY_ESCALATION_CONTACT_REFERENCE",
            "RECOVERY_NOTIFICATION_RECEIVER",
            "RECOVERY_RECEIVER_OWNER_REFERENCE",
            "ALERT_ESCALATION_POLICY_REFERENCE",
            "ALERT_ACKNOWLEDGMENT_TIMEOUT_MINUTES",
            "SECONDARY_ESCALATION_DELAY_MINUTES",
            "MONITORING_APPROVER",
            "AFTER_HOURS_POLICY_REFERENCE",
            "INCIDENT_RESPONSE_OWNER",
            "MONITORING_OWNER",
            "MONITORING_CHANGE_ID",
            "MONITORING_MAINTENANCE_WINDOW",
            "MONITORING_RETENTION_POLICY",
            "API_PERMISSION_APPROVER",
            "DNC_POLICY_REFERENCE",
            "DNC_TEST_APPROVER",
            "RECORDING_POLICY_REFERENCE",
            "RECORDING_RETENTION_POLICY",
            "SECURITY_APPROVER",
            "MAINTENANCE_APPROVER",
            "RISK_ACCEPTANCE_OWNER",
            "PRODUCTION_ACTIVATION_APPROVER",
            "FINAL_CHANGE_ID",
            "FINAL_PRODUCTION_WINDOW",
            "ROLLBACK_DECISION_OWNER",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "governance.env"
            values = {
                key: (
                    "5" if key in {"ALERT_ACKNOWLEDGMENT_TIMEOUT_MINUTES", "SECONDARY_ESCALATION_DELAY_MINUTES"}
                    else f"approved-reference-{index}"
                )
                for index, key in enumerate(keys)
            }
            path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
            result = subprocess.run(
                ["python3", str(MONITORING / "validate-governance.py"), str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("count=29", result.stdout)

    def test_every_critical_alert_has_an_existing_runbook(self) -> None:
        document = yaml.safe_load(
            (MONITORING / "rules" / "platform.rules.yml").read_text()
        )
        critical = [
            rule
            for group in document["groups"]
            for rule in group["rules"]
            if rule.get("labels", {}).get("severity") == "critical"
        ]
        self.assertTrue(critical)
        for rule in critical:
            reference = rule.get("annotations", {}).get("runbook")
            self.assertIsNotNone(reference, rule["alert"])
            self.assertTrue((ROOT / reference).is_file(), f"{rule['alert']}: {reference}")

    def test_alertmanager_uses_only_protected_receiver_files(self) -> None:
        document = yaml.safe_load(
            (MONITORING / "alertmanager.example.yml").read_text()
        )
        protected = [
            receiver for receiver in document["receivers"]
            if receiver["name"].startswith("approved-")
        ]
        self.assertEqual(len(protected), 3)
        for receiver in protected:
            for webhook in receiver["webhook_configs"]:
                self.assertNotIn("url", webhook)
                self.assertTrue(webhook["url_file"].startswith("/run/secrets/"))
                self.assertTrue(webhook["send_resolved"])

    def test_email_provisioning_foreign_keys_match_installed_canonical_ids(self) -> None:
        migration = (
            ROOT / "migrations" / "control_plane" / "003_campaign_email_provisioning.sql"
        ).read_text()
        self.assertIn("format_type(a.atttypid,a.atttypmod)", migration)
        self.assertIn("campaign_id_type NOT IN ('text','uuid')", migration)
        self.assertIn("agent_id_type NOT IN ('text','uuid')", migration)
        self.assertEqual(
            migration.count(
                "%s NOT NULL REFERENCES control_plane.campaign(id)"
            ),
            2,
        )
        self.assertIn("%s NOT NULL REFERENCES control_plane.agent(id)", migration)
        self.assertEqual(migration.count("DROP POLICY IF EXISTS"), 3)


if __name__ == "__main__":
    unittest.main()
