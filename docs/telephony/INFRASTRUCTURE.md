# Telephony infrastructure

Captured on 2026-08-05 on the live host, before any campaign or carrier change.

```text
SERVER_REACHABLE=PASS_LOCAL_PRIVILEGED
OPERATING_SYSTEM=openSUSE Leap 15.6
KERNEL=6.4.0-150600.23.103-default x86_64
CPU=20 logical CPUs, Intel Core i5-13500
RAM=62 GiB
DISK_TOTAL=466 GiB
DISK_FREE=416 GiB
PUBLIC_IP=65.21.67.207/26 (eth0)
PRIVATE_IP=10.40.0.2/24 (eth0.4000)
VSWITCH_STATUS=PASS_ROUTE_10.40.0.0/24
FIREWALL_STATUS=PASS_DEFAULT_REJECT
ASTERISK_STATUS=PASS_18.26.4-vici
VICIDIAL_STATUS=PASS
DATABASE_STATUS=PASS_MARIADB_LOOPBACK_ONLY
WEB_INTERFACE_STATUS=PASS_APACHE
RECORDING_STORAGE_STATUS=PASS_RESTRICTED
MONITORING_STATUS=PASS
BACKUP_STATUS=PASS_ENCRYPTED_OFF_SERVER
```

The host runs Asterisk, MariaDB, Apache, firewalld/nftables, VICIdial daemon
roles, the restricted provisioning adapter, and a passive AMI event publisher.
MariaDB listens on `127.0.0.1:3306`; AMI listens on `127.0.0.1:5038`.
ARI is disabled and no `/ari` URI is registered. Asterisk HTTPS/WSS on 8089
is retained for existing WebRTC endpoints. Plain HTTP 8088 is not allowlisted
by the firewall.

Time synchronization uses chrony and was synchronized at capture with normal
leap status and sub-millisecond offset. The operating system, Asterisk and
VICIdial use `America/New_York`; MariaDB uses `SYSTEM`. Events must carry UTC
timestamps and preserve campaign/customer timezone separately.

## Storage

Live recordings remain under `/var/spool/asterisk/monitor`; no recording path
is published. Governed processing areas are under
`/var/lib/codestra-telephony` with mode 0750 or stricter. Root-only evidence,
exports and configuration backups are separate from service-owned temporary
audio and processed recordings. The filesystem is 7% utilized. The health
monitor alerts at 85%; application retention bounds temporary audio to one day
and exports to 30 days. Filesystem project quotas are not enabled; the disk
threshold and retention policy are the current capacity controls.

## Services and recovery

Critical services use systemd restart policy, dependency ordering, sandboxing,
resource limits, timers and signed readiness checks. Two obsolete OCI staging
units that had entered restart loops were disabled; the native passive gateway
is active on loopback with external delivery disabled.

The daily backup includes the VICIdial database, Asterisk, VICIdial, Apache,
firewall, cron, systemd, log rotation and local operational scripts. Archives
are AES-256-CBC/PBKDF2 encrypted, checksummed, mode 0600, and copied to the
middleware server under `/srv/codestra-backups/vicidial`. An isolated restore
to `codestra_restore_test_20260805` verified 25 campaigns, 44 users and 23
recording rows before the temporary database was removed. Evidence is retained
under `/root/codestra-restore-test-20260805T041200Z`.

```text
SERVER_INVENTORY_STATUS=PASS
NETWORK_SEGMENTATION_STATUS=PASS
FIREWALL_STATUS=PASS
TIME_SYNC_STATUS=PASS
STORAGE_STATUS=PASS_WITH_MONITORED_CAPACITY_CONTROL
RECORDING_STORAGE_STATUS=PASS
SERVICE_MANAGEMENT_STATUS=PASS
MONITORING_STATUS=PASS
BACKUP_STATUS=PASS
ISOLATED_RESTORE_STATUS=PASS
```

