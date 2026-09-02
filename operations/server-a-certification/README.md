# Server A production-readiness controls

This directory is the repository authority for certifying the core Codestra
application host at `65.109.65.169` / `10.40.0.1`. It is intentionally split
from live deployment: merging the source creates reviewed controls; it does not
claim that Server A has passed them.

## Non-negotiable boundary

The package does not modify OpenSSH configuration, keys, listeners, users,
PAM, sudoers, CrowdSec SSH policy, or the SSH service. Installation,
activation, firewall apply, and rollback capture effective SSH configuration,
listeners, authorized-key/configuration hashes, and active sessions. Any change
or loss of a starting session fails the transaction.

No control activates live SMS, email, PSTN, trading, payments, callbacks, or
unapproved n8n execution. Recovery environments use internal Docker networks
and publish no ports.

## Controls

| Area | Source | Runtime result |
|---|---|---|
| Stable encrypted backup | `operations/database-certification/backup-all-databases.py` | `STATUS.json` after GPG encryption/signing, off-host checksum readback, and immutable-retention proof |
| Isolated recovery | `operations/database-certification/restore-all-databases.py` | restored databases, Odoo filestore/config, Keycloak startup, and n8n credential-decryption proof |
| Centrifugo | `centrifugo-probe.py` | explicit internal HTTP, external HTTPS, and WebSocket handshake evidence |
| Financial governance | `publish-governance-status.py` | exact-repository/exact-SHA GitHub status publish and exact status-ID readback |
| Database access | `audit-database-security.py` | complete role/database inventory, no privileged runtime role, and exact CONNECT allowlists |
| Realtime HA | `audit-realtime-ha.py` | recovery/read-only state, system identifier, WAL receiver, replay lag, primary streaming count, and routing fence |
| Odoo copies | `audit-odoo-copy-governance.py` | all production-UUID-derived databases classified, production roles denied from copies, and live DB/filestore bindings aligned |
| Redis | `audit-redis-recovery.py` | classification, persistence configuration, and tested recovery or formally proven safe-loss/rebuild evidence without exporting values |
| Containers | `audit-container-policy.py` | health, restart, CPU, memory, PID, immutable image, and published-port contract |
| Environment separation | `audit-environment-isolation.py` | complete runtime classification and no unapproved cross-environment network, mount, or production-secret sharing |
| Host/Docker perimeter | `firewall/server-a-firewall.py` | default-drop host input, original-port Docker DNAT allowlist, other public forwarding drop, automatic rollback, HTTPS checks, and unchanged SSH state |
| Final certificate | `certify.py` | complete hashed evidence assertions for every required PASS and accepted WARNING |

## Two-stage deployment

### 1. Install reviewed source without starting services

```bash
export CODESTRA_EXPECTED_SOURCE_SHA=<exact-reviewed-commit>
export CODESTRA_SERVER_A_INSTALL_CONFIRM=INSTALL_REPOSITORY_CONTROLS
sudo -E operations/server-a-certification/install.sh --apply
```

The installer requires a clean checkout at the exact commit, writes an
immutable release directory, snapshots prior units/rules/current symlink,
installs but does not start controls, and produces a rollback transaction. It
refuses to replace an already active or enabled generation.

### 2. Remediate runtime failures, then activate

Populate the protected configuration under
`/etc/codestra/server-a-certification/` from the examples. Do not replace
placeholders with guesses. First use `preflight.py`, the existing
`operations/database-rbac/` controls, and component-specific repositories to
repair every failed source/runtime contract.

Activation requires all audits to pass before applying the firewall and before
retiring the broken legacy backup timer:

```bash
export CODESTRA_SERVER_A_ACTIVATE_CONFIRM=ACTIVATE_SERVER_A_CONTROLS
export CODESTRA_ACTIVATE_FIREWALL=YES
export CODESTRA_OUT_OF_BAND_CONSOLE_CONFIRMED=YES
export CODESTRA_FIREWALL_APPLY_CONFIRM=APPLY_SERVER_A_DEFAULT_DENY
sudo -E /opt/codestra/production-controls/current/operations/server-a-certification/activate.sh --apply
```

Activation performs a new encrypted backup, restores the exact off-host copy,
runs ten Centrifugo probes and three governance status/readback cycles, runs the
database/realtime/Odoo/Redis/container/isolation audits, transactionally applies
the firewall, compares SSH state, and only then enables periodic timers. An
activation failure disables the newly enabled timers, restores the previous
firewall snapshot when one was applied, and re-enables the prior backup timer
when it was previously enabled.

### Rollback the repository controls

Use the exact transaction emitted by installation:

```bash
export CODESTRA_SERVER_A_ROLLBACK_CONFIRM=ROLLBACK_SERVER_A_CONTROLS
sudo -E /opt/codestra/production-controls/current/operations/server-a-certification/rollback.sh \
  --apply /opt/codestra/rollback/server-a-certification/<transaction>
```

Rollback restores the previous source symlink, systemd units, and Prometheus
rules. Immutable release artifacts are retained for evidence.

## Certification

`initialize-certification.py` creates a fail-closed input. Every PASS/WARNING
must reference a real root-owned or otherwise non-writable evidence file under
an approved evidence root, include its SHA-256, and assert exact JSON-pointer or
text content. `certify.py` refuses source/installed commit mismatch, absent
evidence, altered evidence, unlisted gates, or a required status other than
PASS.

The only permitted final certified verdict is:

```text
PRODUCTION_CERTIFIED_WITH_ACCEPTED_SSH_SECURITY_EXCEPTION
```

while the owner-directed SSH exception remains. A single-host topology may be a
WARNING only after logical isolation, capacity, backup, recovery, and rollback
pass. A repository merge or successful control activation alone is never a
production certificate.
