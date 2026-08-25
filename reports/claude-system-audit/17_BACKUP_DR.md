# 17 — Backup & Disaster Recovery

Per the mission: *"Documentation claiming that backups exist is insufficient. Check timestamps and restoration evidence."* This report evaluates actual timestamped evidence of backup jobs running AND of restores having been tested — not the presence of scripts/cron entries alone.

## Backup job definition (compose-level)

`/opt/codestra/compose/compose.yaml` defines a `backup` service: image `postgres@sha256:ef257d85f76e...` (pinned digest, good practice), `restart: unless-stopped`, mounting `/opt/codestra/backups:/backups` and read-only source mounts for `postgres_data`, `odoo_data`, `n8n_data`, and the entire `/opt/codestra` config tree. Confirmed running as `codestra-backup-1`, `Up` at audit time (per `01_RUNTIME_INVENTORY.md`).

## Evidence by component (mission Step 21 checklist)

| Component | Backup job exists? | Last successful evidence | Restore tested? |
|---|---|---|---|
| Odoo database | Likely (via `backup` service's `postgres_data`/`odoo_data` mounts) — UNVERIFIED exact schedule, no dedicated Odoo-DB timer found separate from the generic `backup` container | `/opt/codestra/backups` has 188 entries, several from the last 24-72h (e.g. `odoo-mail-inbox-20260823T015300Z`, `contact-center-predeploy-20260823T04*`) — **but these look like ad-hoc pre-change snapshots tied to specific deploys/PRs, not a labeled recurring "odoo-db-daily" job** | **Yes, once** — `/opt/codestra/restore/odoo19-rehearsal-20260723/` contains real pre/post dump files (`codestra_odoo_test.pre-odoo19.dump`, `codestra_odoo_test.post-odoo19.dump`) from an actual restore rehearsal dated 2026-07-23 — **33 days before this audit (2026-08-25)**, not repeated since |
| Odoo filestore | UNVERIFIED — no filestore-specific backup path identified distinct from DB dumps | none found | UNVERIFIED |
| VICIdial database | Backup job confirmed running: `/srv/codestra-backups/vicidial/` contains **daily timestamped folders going back to 2026-08-05**, most recent `20260825T072416Z` — **same-day as this audit**, good cadence evidence | **Current** (today) | UNVERIFIED from this host — restore evidence would live on the VICIdial host itself, see `06_VICIDIAL_ASTERISK.md` for follow-up |
| Asterisk config | Presumably bundled with VICIdial backups above — UNVERIFIED as a distinct artifact | see above | UNVERIFIED |
| Recordings | UNVERIFIED — not confirmed whether call recordings are included in the VICIdial backup set or backed up separately; cross-reference `06_VICIDIAL_ASTERISK.md` | UNVERIFIED | UNVERIFIED |
| Middleware database | Presumed covered by generic `backup` service (`postgres_data` mount is shared across all Postgres-backed services on this host, not component-specific) | see `/opt/codestra/backups`, not individually labeled | UNVERIFIED |
| Kong config | UNVERIFIED — Kong config is DB-backed (`codestra-kong-kong-db-1`, Postgres) so would fall under generic Postgres backup, but no evidence of Kong-specific export (`kong config db_export`) found | UNVERIFIED | UNVERIFIED |
| Caddy config | Version-controlled via numerous `Caddyfile.pre-*`/`Caddyfile.before-*` snapshots found under `/opt/codestra/config/caddy/` (manual pre-change copies, not an automated backup job) | manual snapshots exist, ad hoc | N/A (config, not data — "restore" = redeploy from git, assuming it's tracked, see `03_GITHUB_RUNTIME_RECONCILIATION.md`) |
| n8n database | Presumed covered by `n8n_data` mount in the generic `backup` service | UNVERIFIED specific evidence | UNVERIFIED |
| Email system | UNVERIFIED — `/opt/codestra/mail-platform-backup-20260822-*` and `mail-platform-restore-20260822-*` directories exist (dated 3 days before audit), suggesting a real backup+restore exercise was performed recently for the mail platform specifically — this is one of the stronger pieces of restore evidence found, but contents were not opened in this pass (would require deeper review, flagged for `11_EMAIL.md`) | 2026-08-22 (3 days before audit) | **Likely yes** (dedicated restore dir exists) — confirm in `11_EMAIL.md` |
| SMS config | UNVERIFIED — no SMS-specific backup path identified | UNVERIFIED | UNVERIFIED |
| Keycloak | Presumed covered by generic Postgres backup (`codestra-identity-identity-db-1`) | UNVERIFIED specific evidence | UNVERIFIED |

## Cross-host backup archive

`/srv/codestra-backups/server-b/server-b-essential.enc` (27MB, encrypted, with `SHA256SUMS`) — **last modified 2026-07-24, 32 days before this audit.**

**Finding BKP-P1-01 — The only cross-host/off-box-labeled backup artifact (`server-b-essential.enc`) is 32 days stale, with no visible automation that refreshes it, while every other backup category on this host shows daily or near-daily cadence.**
- Observed evidence: `ls -la /srv/codestra-backups/server-b/` shows `server-b-essential.enc` and `SHA256SUMS` both dated `Jul 24 15:36`, vs. `vicidial/` subfolder showing continuous daily folders through `20260825T072416Z` (today). No systemd timer or cron entry found targeting `server-b` backups (searched `/etc/cron.d`, `systemctl list-timers --all`).
- Expected state: if "server-b" is a meaningful DR artifact (name suggests a second/backup server or a specific host's essential-data snapshot), it should have a defined refresh cadence like the VICIdial backups do.
- Current state: one-time snapshot, un-refreshed for a month, decryption not attempted (per read-only mandate) so contents/currency cannot be verified beyond the file timestamp.
- Risk: if this archive is relied upon for any DR runbook, restoring from it today would restore 32-day-stale state, and nobody would be alerted to that staleness beforehand — it just sits there looking like "we have a backup."
- Recommended fix: identify what `server-b` is and who owns this backup step; either put it on a recurring timer or, if it's genuinely a one-time archive (e.g. decommissioned host preserved for reference), rename/relocate it out of the active backup directory so it isn't mistaken for a live DR artifact.
- Test required: decrypt-and-verify against `SHA256SUMS` (can be done without exposing contents broadly) as part of confirming it's restorable at all.
- Rollback: N/A.
- GitHub repo: backup automation repo (confirm location in `03_GITHUB_RUNTIME_RECONCILIATION.md`). Suggested branch: `ops/server-b-backup-cadence-or-retire`.

## Restore-validation framework

`/opt/codestra/restore-validation/` contains a genuine, structured restore-validation pipeline: staged scripts `00-preflight.sh` → `20-decrypt.sh` → `40-postgres.sh` → `50-restore.sh` → `60-hmac-v2.sh` → `70-health.sh` → `80-rollback.sh` → `90-evidence.sh`, plus `policy.yaml`, cosign key-mount setup, and an `evidence/` directory — this is real engineering investment, not just documentation.

**Finding BKP-P1-02 — The restore-validation pipeline has produced no evidence in 24 days despite being actively built out (multiple staged scripts, HMAC verification, cosign signing).**
- Observed evidence: `ls -lat /opt/codestra/restore-validation/logs` shows the directory itself last modified `Jul 31 18:42`, empty. `ls -lat /opt/codestra/restore-validation/evidence` shows its most recent subdirectory `backup-contract-v2-20260801T113050Z` dated **2026-08-01, 24 days before this audit** — everything older than that in a 13-entry evidence directory, nothing since.
- Expected state: given the sophistication of this pipeline (HMAC verification, cosign signing, rollback stage, structured evidence bundling — this is clearly meant to run regularly, likely per-deploy or on a schedule), a 24-day silence is a regression, not an absence of the capability.
- Current state: pipeline exists and appears complete, but is not currently being exercised. Combined with `01_RUNTIME_INVENTORY.md`'s Finding INV-P2-04 (the `codestra-readiness-backup.timer` and `codestra-readiness-authorization.timer` both went inert around the same period, early August), this looks like a **coordinated readiness/validation subsystem that was live through early August and has since stopped running** — not a case of the capability never having existed.
- Risk: **P1** — the mission explicitly requires restoration evidence, not just backup existence; without recent runs, there is no current evidence that a restore actually works, only that it worked as of a month ago.
- Recommended fix: determine why the pipeline stopped running (was its trigger — likely `codestra-readiness-backup.timer` — disabled deliberately or did it silently break?); re-enable and confirm a fresh evidence bundle is produced.
- Test required: run `00-preflight.sh` through `90-evidence.sh` end-to-end and confirm a new evidence directory is created.
- Rollback: N/A — this is inspection, not a Phase 1 action.
- GitHub repo: wherever `restore-validation` scripts are tracked (confirm in `03_GITHUB_RUNTIME_RECONCILIATION.md` — note this directory itself did not appear in the git-repo scan in `01_RUNTIME_INVENTORY.md`, meaning **it may not be version-controlled at all**, which is itself worth flagging to that report).
- Suggested branch: `ops/reactivate-restore-validation-pipeline`.

## Summary counts for this file

P0: 0 · P1: 2 · P2: 0 · P3: 0
