#!/usr/bin/env python3
"""Generate the authoritative Phase 5A alert rules and alert-specific runbooks."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULE_PATH = ROOT / "operations/monitoring/rules/platform.rules.yml"
RUNBOOK_DIR = ROOT / "operations/runbooks/alerts"
MATRIX_PATH = ROOT / "operations/monitoring/RULE-COVERAGE-MATRIX.tsv"
RUNBOOK_MATRIX_PATH = ROOT / "operations/monitoring/RUNBOOK-COVERAGE.tsv"
THRESHOLD_PATH = ROOT / "operations/monitoring/THRESHOLD-ASSUMPTIONS.md"

# group, alert name, slug, service, environment, expression, duration, threshold,
# summary. Metrics are intentionally exporter-neutral Codestra contract metrics.
CATALOG = [
    ("application", "CodestraMiddlewareUnavailable", "middleware-unavailable", "middleware", "production", 'codestra_service_up{service="middleware"} == 0', "2m", "service_up = 0", "Middleware is unavailable"),
    ("application", "CodestraMiddlewareRestartLoop", "middleware-restart-loop", "middleware", "production", 'increase(codestra_service_restarts_total{service="middleware"}[15m]) >= 3', "5m", "3 restarts / 15m", "Middleware is restarting repeatedly"),
    ("application", "CodestraOdoo19StagingUnavailable", "odoo19-staging-unavailable", "odoo19", "staging", 'codestra_service_up{service="odoo19",environment="staging"} == 0', "5m", "service_up = 0", "Odoo 19 staging is unavailable"),
    ("application", "CodestraN8nStagingUnavailable", "n8n-staging-unavailable", "n8n", "staging", 'codestra_service_up{service="n8n",environment="staging"} == 0', "5m", "service_up = 0", "n8n staging is unavailable"),
    ("application", "CodestraKeycloakUnavailable", "keycloak-unavailable", "keycloak", "production", 'codestra_service_up{service="keycloak"} == 0', "2m", "service_up = 0", "Keycloak is unavailable"),
    ("application", "CodestraPrivateCallbackReceiverUnavailable", "private-callback-receiver-unavailable", "callback", "production", 'codestra_service_up{service="private-callback-receiver"} == 0', "2m", "service_up = 0", "Private callback receiver is unavailable"),
    ("application", "CodestraIntegrationLatencyHigh", "integration-latency-high", "integration", "production", 'histogram_quantile(0.95, sum by(le) (rate(codestra_event_processing_seconds_bucket[10m]))) > 10', "15m", "p95 > 10s / 15m", "Integration processing latency is high"),
    ("application", "CodestraQueueBacklogHigh", "queue-backlog-high", "integration", "production", "codestra_queue_ready_depth > 100", "15m", "ready depth > 100 / 15m", "Queue backlog is high"),
    ("application", "CodestraRetryBacklogHigh", "retry-backlog-high", "integration", "production", "codestra_retry_queue_depth > 25", "15m", "retry depth > 25 / 15m", "Retry backlog is high"),
    ("application", "CodestraDeadLetterBacklog", "dead-letter-backlog", "integration", "production", "codestra_dead_letter_depth > 0 or deriv(codestra_dead_letter_depth[15m]) > 0", "5m", "depth > 0 or growing / 5m", "Dead-letter backlog is nonzero or growing"),
    ("application", "CodestraCallbackFailureRateHigh", "callback-failure-rate-high", "callback", "production", 'sum(rate(codestra_callback_requests_total{result="failure"}[10m])) / clamp_min(sum(rate(codestra_callback_requests_total[10m])), 0.001) > 0.05', "10m", "failure ratio > 5% / 10m", "Callback failure rate is high"),
    ("application", "CodestraDuplicateEventConflict", "duplicate-event-conflict", "integration", "production", "increase(codestra_duplicate_event_conflicts_total[10m]) > 0", "2m", "any conflict / 10m", "Duplicate event conflict detected"),
    ("application", "CodestraEventOrderingConflict", "event-ordering-conflict", "integration", "production", "increase(codestra_event_ordering_conflicts_total[10m]) > 0", "2m", "any conflict / 10m", "Event-ordering conflict detected"),
    ("application", "CodestraReconciliationDrift", "reconciliation-drift", "reconciliation", "production", "codestra_reconciliation_drift_records > 0", "15m", "drift records > 0 / 15m", "Reconciliation drift detected"),
    ("application", "CodestraAuthenticationFailureSurge", "authentication-failure-surge", "identity", "production", "sum(rate(codestra_authentication_failures_total[5m])) > 1", "10m", "rate > 1/s / 10m", "Authentication failures surged"),
    ("application", "CodestraAuthorizationFailureSurge", "authorization-failure-surge", "authorization", "production", "sum(rate(codestra_authorization_failures_total[5m])) > 0.5", "10m", "rate > 0.5/s / 10m", "Authorization failures surged"),
    ("application", "CodestraDncFailClosedEvent", "dnc-fail-closed-event", "compliance", "production", "increase(codestra_dnc_fail_closed_total[5m]) > 0", "1m", "any event / 5m", "DNC fail-closed event detected"),
    ("application", "CodestraTransferAuthorizationDenialSurge", "transfer-authorization-denial-surge", "transfer", "production", "increase(codestra_transfer_denied_total[5m]) >= 3", "5m", "3 denials / 5m", "Transfer authorization denials surged"),
    ("application", "CodestraUnexpectedWorkflowActivation", "unexpected-workflow-activation", "n8n", "production", "codestra_n8n_active_production_workflows > 0", "1m", "active workflows > 0", "Unexpected production workflow activation detected"),
    ("application", "CodestraUnexpectedWriteEnablement", "unexpected-write-enablement", "integration", "production", "codestra_write_enablement{target=~\"odoo|vicidial\"} > 0", "1m", "write enablement > 0", "Unexpected Odoo or VICIdial write enablement detected"),
    ("application", "CodestraUnexpectedSendEventsEnabled", "unexpected-send-events-enabled", "integration", "production", "codestra_safety_flag{flag=\"SEND_EVENTS\"} != 0", "1m", "SEND_EVENTS != 0", "Unexpected SEND_EVENTS=true detected"),
    ("application", "CodestraUnexpectedProductionCallbacksEnabled", "unexpected-production-callbacks-enabled", "callback", "production", "codestra_safety_flag{flag=\"PRODUCTION_CALLBACKS_ENABLED\"} != 0", "1m", "PRODUCTION_CALLBACKS_ENABLED != 0", "Unexpected production callback enablement detected"),
    ("application", "CodestraIntegrationArchitectureViolation", "integration-architecture-violation", "integration-governance", "production", "codestra_integration_architecture_critical_findings > 0", "1m", "critical findings > 0", "Integration architecture constitution violation detected"),
    ("voice", "CodestraVicidialUnavailable", "vicidial-unavailable", "vicidial", "production", 'codestra_service_up{service="vicidial"} == 0', "2m", "service_up = 0", "VICIdial is unavailable"),
    ("voice", "CodestraAsteriskUnavailable", "asterisk-unavailable", "asterisk", "production", 'codestra_service_up{service="asterisk"} == 0', "2m", "service_up = 0", "Asterisk is unavailable"),
    ("voice", "CodestraTrunkUnavailable", "trunk-unavailable", "voice-trunk", "production", "codestra_voice_trunk_up == 0", "2m", "trunk_up = 0", "Voice trunk is unavailable"),
    ("voice", "CodestraCarrierAuthenticationFailure", "carrier-authentication-failure", "carrier", "production", "increase(codestra_carrier_authentication_failures_total[5m]) > 0", "2m", "any failure / 5m", "Carrier authentication failure detected"),
    ("voice", "CodestraUnexpectedActiveCall", "unexpected-active-call", "voice", "production", "codestra_active_calls > 0", "1m", "active calls > 0", "Unexpected active call detected"),
    ("voice", "CodestraUnexpectedExternalDialingEnabled", "unexpected-external-dialing-enabled", "voice", "production", "codestra_safety_flag{flag=\"EXTERNAL_DIAL_ENABLED\"} != 0", "1m", "EXTERNAL_DIAL_ENABLED != 0", "Unexpected external dialing enablement detected"),
    ("voice", "CodestraEndpoint6101Unavailable", "endpoint-6101-unavailable", "sip-endpoint-6101", "production", 'codestra_sip_endpoint_registered{endpoint="6101"} == 0', "2m", "authorized registration = 0", "Endpoint 6101 is unavailable"),
    ("voice", "CodestraEndpoint6101UnauthorizedRegistration", "endpoint-6101-unauthorized-registration", "sip-endpoint-6101", "production", 'codestra_sip_endpoint_unauthorized_registrations{endpoint="6101"} > 0', "1m", "unauthorized registrations > 0", "Endpoint 6101 has an unauthorized registration"),
    ("voice", "CodestraTurnUnavailable", "turn-unavailable", "turn", "production", 'codestra_service_up{service="turn"} == 0', "2m", "service_up = 0", "TURN is unavailable"),
    ("voice", "CodestraTurnAuthenticationFailure", "turn-authentication-failure", "turn", "production", "increase(codestra_turn_authentication_failures_total[5m]) > 0", "2m", "any failure / 5m", "TURN authentication failed"),
    ("voice", "CodestraWssHandshakeFailure", "wss-handshake-failure", "webrtc", "production", "increase(codestra_wss_handshake_failures_total[5m]) >= 3", "5m", "3 failures / 5m", "WSS handshakes are failing"),
    ("voice", "CodestraIceFailure", "ice-failure", "webrtc", "production", "increase(codestra_ice_failures_total[5m]) >= 3", "5m", "3 failures / 5m", "ICE negotiation is failing"),
    ("voice", "CodestraDtlsFailure", "dtls-failure", "webrtc", "production", "increase(codestra_dtls_failures_total[5m]) >= 3", "5m", "3 failures / 5m", "DTLS negotiation is failing"),
    ("voice", "CodestraSrtpFailure", "srtp-failure", "webrtc", "production", "increase(codestra_srtp_failures_total[5m]) >= 3", "5m", "3 failures / 5m", "SRTP setup is failing"),
    ("voice", "CodestraOneWayAudioIndication", "one-way-audio-indication", "voice-media", "production", "increase(codestra_one_way_audio_indications_total[10m]) >= 2", "5m", "2 indications / 10m", "One-way audio is indicated"),
    ("voice", "CodestraPacketLossExcessive", "packet-loss-excessive", "voice-media", "production", "codestra_rtp_packet_loss_ratio > 0.05", "10m", "packet loss > 5% / 10m", "RTP packet loss is excessive"),
    ("voice", "CodestraJitterExcessive", "jitter-excessive", "voice-media", "production", "codestra_rtp_jitter_seconds > 0.05", "10m", "jitter > 50ms / 10m", "RTP jitter is excessive"),
    ("voice", "CodestraCallSetupLatencyExcessive", "call-setup-latency-excessive", "voice", "production", "histogram_quantile(0.95, sum by(le) (rate(codestra_call_setup_seconds_bucket[10m]))) > 8", "10m", "p95 > 8s / 10m", "Call setup latency is excessive"),
    ("voice", "CodestraStuckAsteriskChannel", "stuck-asterisk-channel", "asterisk", "production", "codestra_asterisk_channel_age_seconds > 3600", "5m", "channel age > 1h", "An Asterisk channel appears stuck"),
    ("voice", "CodestraChannelCleanupFailure", "channel-cleanup-failure", "asterisk", "production", "increase(codestra_channel_cleanup_failures_total[10m]) > 0", "5m", "any failure / 10m", "Asterisk channel cleanup failed"),
    ("database-host", "CodestraPostgresqlUnavailable", "postgresql-unavailable", "postgresql", "production", 'codestra_database_up{engine="postgresql"} == 0', "2m", "database_up = 0", "PostgreSQL is unavailable"),
    ("database-host", "MiddlewareDatabaseDown", "middleware-database-down", "middleware-database", "production", 'up{job="postgres-exporter"} == 0 or pg_exporter_last_scrape_error != 0', "2m", "exporter down or scrape error", "Middleware PostgreSQL is unavailable"),
    ("database-host", "MiddlewareDatabaseConnectionWarning", "middleware-database-connection-warning", "middleware-database", "production", 'sum(pg_stat_database_numbackends{datname="codestra_middleware"}) / clamp_min(max(pg_settings_max_connections), 1) > 0.70', "10m", "connections > 70% / 10m", "Middleware database connection utilization is elevated"),
    ("database-host", "MiddlewareDatabaseConnectionCritical", "middleware-database-connection-critical", "middleware-database", "production", 'sum(pg_stat_database_numbackends{datname="codestra_middleware"}) / clamp_min(max(pg_settings_max_connections), 1) > 0.85', "5m", "connections > 85% / 5m", "Middleware database connection utilization is critical"),
    ("database-host", "MiddlewareDatabaseDiskLow", "middleware-database-disk-low", "middleware-database", "production", '(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) > 0.85', "15m", "root filesystem used > 85% / 15m", "Middleware database host disk is low"),
    ("database-host", "MiddlewareDatabaseDeadlocks", "middleware-database-deadlocks", "middleware-database", "production", 'increase(pg_stat_database_deadlocks{datname="codestra_middleware"}[10m]) > 0', "2m", "any deadlock / 10m", "Middleware database deadlock detected"),
    ("database-host", "CodestraMariadbUnavailable", "mariadb-unavailable", "mariadb", "production", 'codestra_database_up{engine="mariadb"} == 0', "2m", "database_up = 0", "MariaDB is unavailable"),
    ("database-host", "CodestraRedisUnavailable", "redis-unavailable", "redis", "production", 'codestra_service_up{service="redis"} == 0', "2m", "service_up = 0", "Redis is unavailable"),
    ("database-host", "CodestraDatabaseConnectionSaturation", "database-connection-saturation", "database", "production", "codestra_database_connections / clamp_min(codestra_database_max_connections, 1) > 0.9", "10m", "connections > 90% / 10m", "Database connection capacity is saturated"),
    ("database-host", "CodestraDiskCapacityCritical", "disk-capacity-critical", "storage", "production", '(1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) > 0.9', "15m", "used > 90% / 15m", "Disk capacity is critically low"),
    ("database-host", "CodestraInodeCapacityCritical", "inode-capacity-critical", "storage", "production", '(1 - node_filesystem_files_free{fstype!~"tmpfs|overlay"} / node_filesystem_files{fstype!~"tmpfs|overlay"}) > 0.9', "15m", "used > 90% / 15m", "Inode capacity is critically low"),
    ("database-host", "CodestraRecordingStorageCapacityCritical", "recording-storage-capacity-critical", "recording-storage", "production", "codestra_recording_storage_used_ratio > 0.9", "15m", "used > 90% / 15m", "Recording-storage capacity is critically low"),
    ("database-host", "CodestraContainerRestartLoop", "container-restart-loop", "containers", "production", "changes(container_start_time_seconds{name=~\"codestra-.+\"}[15m]) >= 3", "5m", "3 restarts / 15m", "A container is restarting repeatedly"),
    ("database-host", "CodestraClockDrift", "clock-drift", "host", "production", "abs(node_timex_offset_seconds) > 0.1 or node_timex_sync_status == 0", "5m", "offset > 100ms or unsynchronized", "Host clock drift is excessive"),
    ("database-host", "CodestraTlsCertificateExpiration", "tls-certificate-expiration", "tls", "production", "probe_ssl_earliest_cert_expiry - time() < 604800", "1h", "expires in < 7d", "TLS certificate expiration is imminent"),
    ("database-host", "CodestraCredentialExpiration", "credential-expiration", "security", "production", "codestra_credential_expiry_timestamp_seconds - time() < 604800", "1h", "expires in < 7d", "A secret or credential expires soon"),
    ("database-host", "CodestraConfigurationDrift", "configuration-drift", "release", "production", "codestra_configuration_drift > 0", "10m", "drift > 0 / 10m", "Runtime configuration drift detected"),
    ("database-host", "CodestraRepositoryDrift", "repository-drift", "release", "production", "codestra_repository_drift > 0", "10m", "drift > 0 / 10m", "Repository drift detected"),
    ("database-host", "CodestraLogIngestionFailure", "log-ingestion-failure", "logging", "production", "codestra_log_ingestion_up == 0", "5m", "ingestion_up = 0", "Log ingestion failed"),
    ("backup", "CodestraBackupFailure", "backup-failure", "backup", "production", "increase(codestra_backup_failures_total[1h]) > 0", "1m", "any failure / 1h", "Backup job failed"),
    ("backup", "CodestraOffServerReplicationFailure", "off-server-replication-failure", "backup", "production", "increase(codestra_backup_replication_failures_total[1h]) > 0", "1m", "any failure / 1h", "Off-server backup replication failed"),
    ("backup", "CodestraBackupChecksumFailure", "backup-checksum-failure", "backup", "production", "increase(codestra_backup_checksum_failures_total[1h]) > 0", "1m", "any failure / 1h", "Backup checksum verification failed"),
    ("backup", "CodestraBackupStale", "backup-stale", "backup", "production", "time() - codestra_backup_last_success_timestamp_seconds > 93600", "15m", "age > 26h / 15m", "Latest successful backup is stale"),
    ("backup", "MiddlewareDatabaseBackupStale", "middleware-database-backup-stale", "middleware-database", "production", "time() - codestra_middleware_backup_last_success_timestamp_seconds > 86400", "15m", "age > 24h / 15m", "Middleware database backup is stale"),
    ("backup", "MiddlewareDatabaseBackupFailed", "middleware-database-backup-failed", "middleware-database", "production", 'codestra_systemd_timer_failed{timer="codestra-scraper-middleware-backup.timer"} > 0 or increase(codestra_backup_replication_failures_total[1h]) > 0', "1m", "timer or replication failure", "Middleware database backup failed"),
    ("backup", "MiddlewareDatabaseRestoreOverdue", "middleware-database-restore-overdue", "middleware-database", "production", "time() - codestra_restore_test_last_success_timestamp_seconds > 2592000", "1h", "restore rehearsal age > 30d", "Middleware database restore rehearsal is overdue"),
    ("backup", "MiddlewareDatabaseMigrationMismatch", "middleware-database-migration-mismatch", "middleware-database", "production", 'codestra_middleware_database_migration_match == 0', "5m", "migration match = 0", "Middleware database migration head mismatches the approved release"),
    ("backup", "CodestraRemoteBackupCapacityLow", "remote-backup-capacity-low", "backup", "production", "codestra_backup_remote_free_bytes < 10737418240", "30m", "free < 10GiB / 30m", "Remote backup capacity is low"),
    ("backup", "CodestraBackupTimerDisabled", "backup-timer-disabled", "backup", "production", "codestra_systemd_timer_enabled{timer=\"codestra-backup.timer\"} == 0", "5m", "timer enabled = 0", "Backup timer is disabled"),
    ("backup", "CodestraBackupTimerFailed", "backup-timer-failed", "backup", "production", "codestra_systemd_timer_failed{timer=\"codestra-backup.timer\"} > 0", "2m", "timer failed > 0", "Backup timer failed"),
    ("backup", "CodestraRestoreTestAgeExceeded", "restore-test-age-exceeded", "recovery", "production", "time() - codestra_restore_test_last_success_timestamp_seconds > 2592000", "1h", "age > 30d", "Restore-test age exceeded"),
    ("backup", "CodestraEncryptionKeyExpiration", "encryption-key-expiration", "backup-security", "production", "codestra_backup_encryption_key_expiry_timestamp_seconds - time() < 2592000", "1h", "expires in < 30d", "Backup encryption key expires soon"),
    ("backup", "CodestraSshHostKeyMismatch", "ssh-host-key-mismatch", "backup-security", "production", "increase(codestra_backup_ssh_host_key_mismatch_total[1h]) > 0", "1m", "any mismatch / 1h", "Backup SSH host-key mismatch detected"),
]

WARNING_COMPANIONS = {
    "CodestraIntegrationLatencyHigh": ("> 5", "p95 > 5s / 15m"),
    "CodestraQueueBacklogHigh": ("> 50", "ready depth > 50 / 15m"),
    "CodestraRetryBacklogHigh": ("> 10", "retry depth > 10 / 15m"),
    "CodestraDatabaseConnectionSaturation": ("> 0.8", "connections > 80% / 15m"),
    "CodestraDiskCapacityCritical": ("> 0.8", "used > 80% / 30m"),
    "CodestraInodeCapacityCritical": ("> 0.8", "used > 80% / 30m"),
    "CodestraRecordingStorageCapacityCritical": ("> 0.8", "used > 80% / 30m"),
    "CodestraTlsCertificateExpiration": ("< 1209600", "expires in < 14d"),
    "CodestraRemoteBackupCapacityLow": ("< 21474836480", "free < 20GiB / 1h"),
    "CodestraRestoreTestAgeExceeded": ("> 1814400", "age > 21d"),
}


def metric_expr_for_warning(alert: str, expr: str, replacement: str) -> str:
    if alert == "CodestraIntegrationLatencyHigh":
        return expr.rsplit(">", 1)[0] + replacement
    if alert in {"CodestraQueueBacklogHigh", "CodestraRetryBacklogHigh"}:
        return expr.rsplit(">", 1)[0] + replacement
    if alert == "CodestraDatabaseConnectionSaturation":
        return expr.rsplit(">", 1)[0] + replacement
    if alert in {"CodestraDiskCapacityCritical", "CodestraInodeCapacityCritical"}:
        return expr.rsplit(">", 1)[0] + replacement
    if alert == "CodestraRecordingStorageCapacityCritical":
        return expr.rsplit(">", 1)[0] + replacement
    if alert == "CodestraTlsCertificateExpiration":
        return expr.rsplit("<", 1)[0] + replacement
    if alert == "CodestraRemoteBackupCapacityLow":
        return expr.rsplit("<", 1)[0] + replacement
    if alert == "CodestraRestoreTestAgeExceeded":
        return expr.rsplit(">", 1)[0] + replacement
    raise ValueError(alert)


def make_rule(item: tuple[str, ...]) -> dict:
    group, alert, slug, service, environment, expr, duration, threshold, summary = item
    runbook = f"operations/runbooks/alerts/{slug}.md"
    return {
        "alert": alert,
        "expr": expr,
        "for": duration,
        "labels": {
            "severity": "critical",
            "service": service,
            "environment": environment,
            "owner_ref": "monitoring-owner-registry",
        },
        "annotations": {
            "summary": summary,
            "description": f"{summary}. Investigate using the linked runbook; preserve safety interlocks and evidence.",
            "current_value": "{{ $value }}",
            "threshold": threshold,
            "threshold_status": "candidate_requires_post_deployment_tuning",
            "runbook": runbook,
            "runbook_url": f"https://runbooks.codestra.agency/alerts/{slug}",
            "dashboard": f"monitoring-evidence://{group}/{slug}",
        },
    }


def safety_text(group: str, slug: str) -> tuple[str, str]:
    prohibited = (
        "Do not enable calls, callbacks, transfers, external dialing, production workflows, "
        "queue delivery, or Odoo/VICIdial writes. Do not expose credentials or personal contact data."
    )
    immediate = "Keep every production safety flag false and isolate the affected component before recovery."
    if group == "voice":
        immediate = "Keep EXTERNAL_DIAL_ENABLED=false and TRANSFERS_ENABLED=false; isolate signaling/media checks from any carrier dial path."
        prohibited += " Never place an uncontrolled test call or register an unapproved endpoint."
    if "queue" in slug or "event" in slug or "reconciliation" in slug or "callback" in slug:
        immediate += " Keep the 1,110 historical events quarantined and immutable."
        prohibited += " Never deliver, replay, reorder, delete, archive, reject, or mutate any of the 1,110 quarantined historical events."
    if "dnc" in slug:
        immediate = "Fail closed: keep dialing and transfers disabled whenever DNC state is uncertain."
        prohibited += " Never bypass, assume, cache over, or weaken a DNC decision."
    return immediate, prohibited


def write_runbook(item: tuple[str, ...]) -> None:
    group, alert, slug, service, environment, expr, duration, threshold, summary = item
    immediate, prohibited = safety_text(group, slug)
    body = f"""# {summary}

Alert name: `{alert}`
Escalation-owner reference: `monitoring-owner-registry` (resolve through the approved protected owner record; never place personal contact information here).

## 1. Alert meaning

Prometheus observed `{expr}` continuously for `{duration}`. The candidate critical threshold is `{threshold}` and requires post-deployment tuning against measured production baselines.

## 2. Immediate safety action

{immediate}

## 3. Impact

The `{service}` service may be unavailable, unsafe, degraded, or unable to satisfy its recovery objective. Treat the metric as an indication to verify, not as authorization to activate traffic.

## 4. Verification commands

Run read-only checks from the approved administration path:

```sh
curl --fail --silent --show-error http://127.0.0.1:9090/api/v1/alerts
curl --fail --silent --show-error 'http://127.0.0.1:9090/api/v1/query?query={alert}'
docker ps --filter label=com.docker.compose.project=codestra-monitoring
journalctl --since '-30 min' --no-pager --output=short-iso
```

Filter output before preservation; do not print environment files, headers, tokens, payloads, telephone numbers, or recordings.

## 5. Likely causes

Exporter or probe failure; dependency outage; capacity exhaustion; credential expiry; configuration drift; network/TLS failure; a failed deployment; or a genuine safety-control violation.

## 6. Staging versus production

This rule is scoped to `{environment}`. Staging alerts may use isolated test routes only. Production alerts must use approved production routes only. Never promote a staging result, receiver, credential, or threshold as production-proven.

## 7. Recovery procedure

1. Preserve alert, metric, relevant redacted logs, config/image digests, and timestamps.
2. Confirm the signal through a second read-only source.
3. Correct the smallest identified cause without changing safety flags.
4. For queues, reconcile metadata read-only and leave quarantined records untouched.
5. Observe the metric below threshold for at least `{duration}` and verify the resolved notification through the approved route.

## 8. Rollback procedure

Restore the last approved non-secret monitoring configuration or application release using its recorded digest. Validate configuration before reload. If rollback would enable delivery, dialing, workflows, or writes, stop and invoke the external approval process.

## 9. Emergency-disable conditions

Disable or isolate only the affected application path when safety flags change unexpectedly, DNC state is uncertain, unauthorized registration/call activity appears, data integrity is in doubt, or recovery increases impact. Do not disable monitoring evidence collection unless it is the direct cause.

## 10. Expected resolved signal

The alert is absent from `/api/v1/alerts`, its expression remains false for `{duration}`, and Alertmanager records a resolved notification after receiver recovery without claiming false delivery.

## 11. Evidence to preserve

Alert fingerprint and labels; query result; UTC first/last timestamps; redacted Prometheus/Alertmanager/application logs; config and image digests; operator actions; rollback decision; resolved-delivery evidence. Preserve no secrets or personal contact details.

## 12. Escalation-owner reference

`monitoring-owner-registry`. Resolution is fail-closed when the protected owner record or escalation policy is missing.

## 13. Actions that must not be performed

{prohibited}
"""
    (RUNBOOK_DIR / f"{slug}.md").write_text(body)


def main() -> None:
    RUNBOOK_DIR.mkdir(parents=True, exist_ok=True)
    expected = {f"{item[2]}.md" for item in CATALOG}
    for path in RUNBOOK_DIR.glob("*.md"):
        if path.name not in expected:
            path.unlink()

    groups: dict[str, list[dict]] = {}
    for item in CATALOG:
        groups.setdefault(item[0], []).append(make_rule(item))
        write_runbook(item)
        alert = item[1]
        if alert in WARNING_COMPANIONS:
            replacement, threshold = WARNING_COMPANIONS[alert]
            warning = make_rule(item)
            warning["alert"] = alert.removesuffix("Critical").removesuffix("High") + "Warning"
            warning["expr"] = metric_expr_for_warning(alert, item[5], replacement)
            warning["for"] = "30m"
            warning["labels"]["severity"] = "warning"
            warning["annotations"]["summary"] = f"Early warning: {item[8].lower()}"
            warning["annotations"]["threshold"] = threshold
            groups[item[0]].append(warning)

    RULE_PATH.write_text(yaml.safe_dump(
        {"groups": [{"name": name, "rules": rules} for name, rules in groups.items()]},
        sort_keys=False,
        width=1000,
    ))

    with MATRIX_PATH.open("w", newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(("required_class", "alertname", "severity", "service", "environment", "threshold", "for", "runbook", "status"))
        for item in CATALOG:
            writer.writerow((item[2], item[1], "critical", item[3], item[4], item[7], item[6], f"operations/runbooks/alerts/{item[2]}.md", "COVERED"))

    with RUNBOOK_MATRIX_PATH.open("w", newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(("alertname", "runbook", "required_sections", "owner_reference", "status"))
        for item in CATALOG:
            writer.writerow((item[1], f"operations/runbooks/alerts/{item[2]}.md", "13/13", "monitoring-owner-registry", "PASS"))

    rows = "\n".join(
        f"| `{item[1]}` | `{item[7]}` | `{item[6]}` | candidate; tune after deployment |"
        for item in CATALOG
    )
    THRESHOLD_PATH.write_text(f"""# Threshold assumptions

Generated from the authoritative catalog. Existing measured values were retained where documented: backup staleness 26 hours, backup remote free capacity 10 GiB, host capacity 90%, database critical saturation 90%, TLS critical expiry 7 days, and restore-test maximum age 30 days. Other values are deliberately conservative candidate thresholds.

No threshold in this file is claimed to be production-proven. Every rule carries `threshold_status=candidate_requires_post_deployment_tuning`. `for:` periods, grouping, and warning companions for capacity/latency controls limit alert storms. Safety-control violations intentionally use short durations. Warning and critical thresholds are distinct for integration latency, queue/retry backlog, database saturation, disk/inodes/recording storage, TLS expiry, remote backup capacity, and restore-test age.

| Alert | Critical threshold | `for` | Basis |
|---|---|---:|---|
{rows}
""")
    print(f"generated critical={len(CATALOG)} warning={len(WARNING_COMPANIONS)} runbooks={len(CATALOG)}")


if __name__ == "__main__":
    main()
