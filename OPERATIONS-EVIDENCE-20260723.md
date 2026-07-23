# Codestra backup and monitoring operations evidence

Evidence date: `2026-07-23`  
Host: `middleware`  
Branch: `feature/callcenter-platform-19`

## Implemented

```text
OPERATIONS_FRAMEWORK_COMMIT=bc8fb3048309970b1acba798993f7d349a5038e6
ALERT_DELIVERY_TEST_COMMIT=b0e7c87cdf035256209d593a832a5181e101d3c5
BACKUP_FAIL_CLOSED=PASS
BACKUP_UNIT_TESTS=PASS_4_OF_4
BACKUP_ENCRYPTION=GPG_RECIPIENT_REQUIRED
BACKUP_REPLICATION=STRICT_HOST_KEY_SCP_REQUIRED
BACKUP_DATABASES=ODOO_MIDDLEWARE_N8N_KEYCLOAK
BACKUP_ODOO_FILESTORE=INCLUDED_WITH_QUIESCED_ODOO
BACKUP_N8N_DATA_AND_ENCRYPTION_KEY_SOURCE=INCLUDED_IN_ENCRYPTED_BUNDLE
BACKUP_CONFIGURATION=INCLUDED_SANITIZED_AND_PROTECTED_SEPARATELY
BACKUP_RETENTION=REPORT_ONLY_NEVER_AUTODELETES
BACKUP_MINIMUM_VALID_COPIES=2
BACKUP_FRESHNESS_THRESHOLD_SECONDS=93600
BACKUP_CAPACITY_THRESHOLD_BYTES=10737418240
SYSTEMD_SERVICE_AND_TIMER_SYNTAX=BASH_AND_UNIT_CONTENT_VALIDATED
```

The backup job refuses to run unless the approved GPG recipient, remote host
and directory, SSH identity, and strict known-hosts file are configured. Odoo,
n8n, middleware, and Keycloak are paused only for the bounded capture window
and resumed by traps on success or failure. Plaintext staging material is
restricted by umask and removed through an exact validated work-directory
pattern. The encrypted artifact is checksum-verified before replication.

Cleanup is intentionally report-only. It verifies checksums, refuses to
proceed with fewer than two valid backups, and never deletes a backup.

## Monitoring validation

```text
PROMETHEUS_VERSION=3.13.1
ALERTMANAGER_VERSION=0.33.1
NODE_EXPORTER_VERSION=1.12.1
BLACKBOX_EXPORTER_VERSION=0.28.0
CADVISOR_VERSION=0.55.1
ALL_IMAGES=PINNED_BY_DIGEST
PROMETHEUS_CONFIG=PASS
PROMETHEUS_RULE_FILES=PASS_1
PROMETHEUS_ALERT_RULES=PASS_29
ALERTMANAGER_EXAMPLE_CONFIG=PASS
PLACEHOLDER_RECEIVER_DEPLOYMENT=REJECTED_EXIT_2
ISOLATED_ALERT_FIRING_RECEIPT=PASS
ISOLATED_ALERT_RECOVERY_RECEIPT=PASS
PRODUCTION_ALERT_RECEIVER=BLOCKED_PROTECTED_DESTINATION_ABSENT
MONITORING_PRODUCTION_DEPLOYMENT=NOT_RUN_FAIL_CLOSED
```

Coverage includes host availability, CPU, memory, disk, inodes, clock
synchronization, container presence/restarts, endpoint health/latency, TLS
expiry, database availability/saturation, dead letters, retries, event
latency/failures, reconciliation drift, authentication/authorization failures,
DNC fail-closed decisions, unauthorized transfers, unexpected workflow and
campaign activation, configuration drift, log ingestion, backup age/failure,
and replication failure.

An isolated loopback-only Alertmanager test delivered a synthetic
`CodestraSyntheticDeliveryTest` notification with `status=firing` and then a
recovery notification with `status=resolved`. The test containers and receiver
were stopped afterward.

## External blockers

The following values cannot be fabricated and are required before enabling
the timers or monitoring deployment:

1. Approved GPG backup recipient fingerprint and available public key.
2. Approved off-server SSH destination, identity, strict known-host entry, and
   remote retention ownership.
3. Approved production alert receiver and escalation route.
4. Operator-approved maintenance timing for the bounded application quiesce.

No backup timer or monitoring stack was enabled with placeholder values.

## Configuration checksums

```text
BACKUP_SCRIPT_SHA256=c886ea827eec56938f59c4e67ec5d06f2cc05eb5a7337c637b24275274776652
MONITORING_COMPOSE_SHA256=0c0a3bba1910fa6ab1cddc345198ab94b380613a04b380c8a03df64dd05131de
ALERT_RULES_SHA256=85cb81fd053379b89d9b6a255b9fa2cd67fda854c7730a6abca6a70b20f2c4a0
```

