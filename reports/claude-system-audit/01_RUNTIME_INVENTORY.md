# 01 — Runtime Inventory (Server: codestra-app / "middleware")

Scope: local host only (hostname `middleware`, public IP `65.109.65.169`, private VLAN IP `10.40.0.1`). VICIdial host (`codestra-vicidial`, 10.40.0.2) is covered in `06_VICIDIAL_ASTERISK.md`. Provider (10.40.0.4) and scraper (10.40.0.3) hosts are explicitly out of scope per user decision.

All evidence gathered read-only: `uname`, `lscpu`, `free`, `df`, `lsblk`, `systemctl`, `ss`, `docker`, `crontab`, filesystem listings, and non-destructive `git status`/`git remote -v` on server-side checkouts.

## Host

| Property | Value |
|---|---|
| OS | Ubuntu 22.04.5 LTS (jammy), kernel 5.15.0-187-generic |
| CPU | AMD Ryzen 5 3600, 6c/12t |
| RAM | 62 GiB total, 10 GiB used, 46 GiB buff/cache, 51 GiB available |
| Swap | 31 GiB, 36 MiB used |
| Root disk | `/dev/md2` (RAID1, 2×nvme), ext4, 436G total, **346G used (84%)**, 68G avail |
| Boot | `/dev/md1` RAID1, 989M, 28% used |
| Uptime | 14 days, 8h (at time of audit) |

**Finding INV-P2-01** — Root filesystem at 84% utilization with a single overlay2 Docker storage backing 100+ historical container rootfs entries observed (`docker ps -a` returns 234 containers, the overwhelming majority `Exited` — staging/canary/rollback/fixture/test artifacts, e.g. `middleware-fixture-6198-*` ×6, `crm-os-cert-*` ×15, `n8n-runtime-canary-*` ×10, `odoo19-migration-20260725*` ×9). No evidence of a docker prune/retention policy.
- Risk: disk exhaustion under continued agent-driven build/test churn; 68G headroom on an 84%-full volume with continuous image builds is thin.
- Recommended fix: establish a retention policy (e.g. `docker system prune` cron with age filter, or explicit teardown step at end of each remediation branch's lifecycle) and prune superseded images.
- Test required: confirm prune script doesn't remove volumes still referenced by running services.
- Rollback: N/A (cleanup only).
- Repo: `codestra-production-platform` — suggested branch: `ops/docker-retention-policy`.

## Docker

- Docker Engine + Compose v2 present. 234 containers total (docker ps -a); **~62 currently `Up`**, remainder `Exited` (mostly `(0)` clean exits from one-off remediation/test runs).
- 60+ `docker network ls` entries, mostly one per Compose project (`codestra-*`, `crm-os-*`, `rc4-*`, `phase-n8-*`, `odoo19-migration-*`). Most are per-project bridges; many show `DOWN` (no active endpoints) — stale networks left behind by torn-down projects.
- Compose files: 50+ under `/opt/codestra/compose/*.yaml`, including numbered/dated one-offs (`compose.cod-web-out-3e6de6e.yaml`, `compose.campaign-crm-7d5b9a4.yaml`, several `rc4-*` staged/production variants) alongside the apparent canonical `/opt/codestra/compose/compose.yaml`. No single obviously-authoritative compose file naming convention — see Finding INV-P2-02.

**Finding INV-P2-02** — Compose sprawl: 50+ compose files under `/opt/codestra/compose/`, many named after specific PRs/fixtures/dates (`compose.m07-exact-digest.yaml`, `compose.schema2-recovery-20260812.yaml`, `rc4-atomic-production-deployment-*`) rather than a clear "this is what's live" file.
- Risk: no reliable way to determine, from the filesystem alone, which compose definition is authoritative for the current running stack; increases risk of drift and of a future deploy picking up a stale/experimental compose file.
- Recommended fix: consolidate to `compose.yaml` + documented override files only; move historical/one-off compose files to an archive path outside the active compose directory.
- Test required: `docker compose config` against the canonical file reproduces exactly the current running container set.
- GitHub repo: `codestra-production-platform` (or wherever compose is tracked — confirm in Step 2 reconciliation). Suggested branch: `ops/compose-consolidation`.

### Live containers by function (from `docker ps`, port column = host bind if published)

| Function | Container(s) | Port binding |
|---|---|---|
| Edge/reverse proxy | host `caddy.service` (systemd, NOT a container) | `65.109.65.169:80/443`, `10.40.0.1:80/443`, `127.0.0.1:80/443` |
| Internal Caddy proxies | `codestra-caddy-upstream-gateway`, `codestra-n8n-internal-proxy`, `codestra-odoo-internal-proxy`, `codestra-private-vicidial-ingress-1`, `codestra-odoo19-module-staging-callback-tls-1` | mostly unpublished / 127.0.0.1 loopback ranges (18101-18116), vicidial-ingress on `10.40.0.1:443` |
| Odoo | `codestra-odoo-1` (prod-labeled) + **7 more** Odoo variants: `codestra-odoo19-staging-*` (×4), `codestra-odoo-staging-odoo-staging-1`, `codestra-odoo19-module-staging-odoo-1`, `codestra-odoo19-identity-menu-staging-postgres-1` | none published externally (8069 internal only) |
| Middleware (core + workers) | `codestra-middleware-1` + **17** worker/adapter containers (`vicidial-adapter`, `pjsip-adapter`, `telephony-provisioning`, `extension-allocator`, `webphone-session-issuer`, `event-gateway`, `external-webhook-worker`, `reconciliation-worker`, `sync-worker`, `policy-engine`, `evidence-runner`, `n8n-runtime-worker`, `social-n8n-delivery-worker`, `breero-odoo-worker`, `postly-polling-worker`, `scraper-odoo-delivery-worker`, `notification-worker`, `scheduler`) all image `1a9e13a0c930`/`73fe86858d7a` family | `10.40.0.1:8095` (main API only); workers unpublished |
| Middleware STAGING (parallel stack) | `codestra-middleware-staging-*` ×5 | `127.0.0.1:31883` |
| Kong | `codestra-kong-kong-gateway-1`, `codestra-kong-kong-db-1`, `codestra-kong-kong-test-upstream-1`, plus standby/adapter: `kong-production-standby-kong-standby-auth-1`, `codestra-kong-service-auth-adapter-1`, `codestra-kong-identity-certification-1` | `127.0.0.1:8000-8002` |
| Identity | `codestra-identity-keycloak-1`, `codestra-identity-auth-gateway-1`, `codestra-provisioning-jwks-relay`, + full parallel `codestra-identity-staging-*` stack | unpublished (8080/8443 internal) |
| n8n | `codestra-n8n-1` + full parallel `codestra-n8n-staging-*` stack (main/webhook/worker×2/redis/postgres) | unpublished (5678 internal) |
| Email | `codestra-mail-api-mail-api-1`, `codestra-mail-isolated-stalwart-1`, `codestra-email-reseller-api-1`, `codestra-beyvra-email-api-1` | `127.0.0.1:2587/2993/28080/28443/18180` |
| SMS | `codestra-sms-api-api-1`, `codestra-sms-api-event-worker-1`, `codestra-sms-api-postgres-1` | unpublished (8080 internal) |
| WebSocket gateway | `codestra-websocket-gateway-gateway-1` + `-migrate`, + `codestra-websocket-standby-031447a-*` (standby copy, one container flapping — see below) | unpublished |
| Agent desktop | `codestra-agent-desktop-sipjs-staging` (live), `codestra-agent-desktop-preview`, plus **3 retained rollback images** (`-rollback-m11-*`, `-rollback-m06-*`, `-rollback-20260817`, all `Exited`) | `127.0.0.1:31881`, `127.0.0.1:31880` |
| Control plane | `codestra-integration-control-plane-api-1/-worker-1`, plus `codestra-cp-candidate-api` (currently **`Restarting (1)`** — crash-looping, see Finding), `codestra-control-plane-hardening-readiness`/`-87abe2a-readiness` (exited 137 = SIGKILL, both) | `127.0.0.1:8096` |
| Reseller portal | `codestra-reseller-portal-portal-1`, `-oidc-gateway-1`, `-postgres-1` | `127.0.0.1:18081` |
| Private integration gateway | `private-integration-gateway-1` | `10.40.0.1:8095` (network_mode `codestra_edge`) |
| Monitoring | `codestra-monitoring-{alertmanager,node-exporter,cadvisor,blackbox,receiver}` **up**; `codestra-monitoring-prometheus-1` **Exited** (see `16_OBSERVABILITY.md`) | internal |
| Postgres instances | `codestra-postgres-1`, `codestra-kong-kong-db-1`, `codestra-identity-identity-db-1`, `codestra-sms-api-postgres-1`, `codestra-reseller-portal-postgres-1`, `codestra-websocket-gateway-postgres-1`, `codestra-middleware-staging-postgres-1`, `codestra-n8n-staging-postgres-1`, `codestra-odoo19-*-postgres-1` (×5), `codestra-backup-1` | all unpublished except loopback-bound where noted |
| Redis | `codestra-redis-1`, `codestra-middleware-staging-redis-1`, `codestra-n8n-staging-redis-1` | unpublished |
| NATS | host-level `nats-server` (systemd, not containerized) | `127.0.0.1:4222`, `127.0.0.1:8222` (monitoring) |

**Finding INV-P1-01** — `codestra-cp-candidate-api` is in a **crash-restart loop** (`Restarting (1)` at time of audit, image `codestra/control-plane:7bed512`), sitting alongside its own `codestra-cp-candidate-db` which is `Exited`. This is a "candidate" deployment left running/crash-looping on the production host rather than in an isolated environment.
- Risk: continuous restart consumes CPU/log space; unclear if this candidate has any traffic routed to it via Kong/Caddy (needs cross-check in `08_KONG.md`/`09_CADDY.md`); an abandoned crash-looping candidate is itself evidence of an unfinished/uncommitted deployment attempt.
- Recommended fix: determine owner/intent of `cp-candidate`; either fix or tear down the candidate stack (`docker compose -p codestra-cp-candidate down`) — do NOT do this without human sign-off, it wasn't authorized in Phase 1.
- Test required: confirm no live route points at this candidate before removal.
- Rollback: N/A, read-only audit.
- Repo: unknown — control-plane repo (needs 03 GitHub reconciliation confirmation). Suggested branch: `ops/remove-cp-candidate-orphan`.

**Finding INV-P2-03** — `codestra-websocket-standby-031447a-gateway-1` shows `health: starting` with **"Up Less than a second"** at time of audit (repeatedly restarting), while its sibling `-migrate-1` and `-postgres-1` are `Exited`. A "standby" WebSocket gateway that can't hold a healthy state is not a usable failover target.
- Risk: if this standby is meant to be the failover path for the primary `codestra-websocket-gateway-gateway-1`, DR/failover claims for the WebSocket layer (used for inbound screen-pop, Step 6) are unverified/likely false.
- Recommended fix: investigate startup failure (`docker logs codestra-websocket-standby-031447a-gateway-1`), fix or formally decommission the standby.
- Test required: manual failover drill once healthy.
- Repo: websocket-gateway repo (confirm in 03). Suggested branch: `fix/websocket-standby-startup-crash`.

## Systemd services (host-level, non-Docker)

Running: `caddy.service` (public edge, NOT the same as the `codestra-caddy-upstream-gateway` container), `nats-server.service`, `fail2ban.service` (jail: `sshd` only — no application-layer jail), `docker.service`, `containerd.service`, `ssh.service`, standard Ubuntu base services (cron, dbus, systemd-*, mdmonitor/multipathd for the RAID1 array, irqbalance, unattended-upgrades).

**Finding INV-P3-01** — `fail2ban` protects only SSH (`sshd` jail). No jail for the public-facing Caddy edge, Kong, Keycloak, or any application login endpoint — brute-force/credential-stuffing protection at the app layer relies entirely on whatever Kong/Keycloak/app-level rate limiting exists (verify in `08_KONG.md`/`10_IDENTITY.md`).

## Systemd timers (scheduled jobs)

Active and recently firing: `codestra-postly-poller.timer` (~1 min), `codestra-crl-metrics.timer`, `codestra-recovery-metrics.timer`, `public-tls-monitor.timer` (~hourly), `codestra-scraper-middleware-backup.timer` (daily), `codestra-cert-monitor.timer`, `codestra-certificate-renewal.timer` (daily).

**Finding INV-P2-04** — Three timers show `NEXT=n/a` (disabled/inert) with stale last-run timestamps: `codestra-qwen-handoff-cleanup.timer` (last ran 2026-08-05, 3 weeks ago), `codestra-readiness-authorization.timer` (last ran 2026-08-04), `codestra-readiness-backup.timer` (last ran 2026-08-03), `codestra-readiness-staging-tls.timer` (last ran 2026-08-03).
- Risk: named "readiness-backup" and "readiness-authorization" — if these were ever part of the production-readiness gate/backup chain, they have been silently inert for 3+ weeks with no visible alerting on that fact (ties to `16_OBSERVABILITY.md` gap).
- Recommended fix: confirm whether these timers are intentionally retired (rename/remove) or accidentally disabled (re-enable); if retired, remove their unit files to avoid confusion.
- Test required: N/A (config hygiene).
- Repo: N/A (systemd unit, not in a code repo — itself a finding, see `03_GITHUB_RUNTIME_RECONCILIATION.md`, host-only config that IaC doesn't track).
- Suggested branch: `ops/audit-inert-timers`.

Standard Ubuntu timers present and firing normally: `apt-daily(-upgrade).timer`, `fstrim.timer`, `e2scrub_all.timer`, `logrotate.timer`, `man-db.timer`, `mdcheck_*.timer` (RAID scrub), `dpkg-db-backup.timer`.

crontab: no user crontab for root; `/etc/cron.d/e2scrub_all` only (stock Ubuntu, unrelated to Codestra).

## Message queues / pub-sub

- **NATS** running host-level (not containerized), bound `127.0.0.1:4222` (client) and `127.0.0.1:8222` (monitoring HTTP) — loopback-only, not directly reachable from other mesh hosts. Used by (needs confirmation in `07_MIDDLEWARE.md`) — flagged for that fork to confirm which middleware workers depend on it and whether single-instance NATS (no cluster) is a SPOF for event delivery.
- **Redis** ×3 instances (main, middleware-staging, n8n-staging) — used as queue/cache backing for n8n and middleware; single-instance each, no visible Sentinel/cluster config (confirm in `13_N8N.md`/`07_MIDDLEWARE.md`).

## Git repositories under `/opt/codestra` (Step 1 requirement — branch/SHA/dirty state)

15 git repos found under `/opt/codestra` (searched `/opt`, `/srv`, `/home`; none found outside `/opt/codestra`). **Full remote/branch reconciliation against GitHub is in `03_GITHUB_RUNTIME_RECONCILIATION.md`** — this table is the raw local `git status` evidence:

| Path | Remote | Branch | SHA (short) | Dirty files |
|---|---|---|---|---|
| `middleware` | `github.com/Codestra-SRL/codestra-middleware` | `postiz-social-orchestration-20260804` | `7b9451b` | **15** |
| `identity-platform` | *(none configured)* | `feature/callcenter-platform-19` | `791b706` | **5** |
| `contact-center-middleware` | *(none / no HEAD)* | — | — | **3** (repo has no commits yet, or detached with no ref) |
| `bitbucket-codestra` | `bitbucket-backup → bitbucket.org/codestra902101/codestra` | `agent/github-migration` | `62b353a` | 0 (clean) |
| `agent-desktop` | **`origin` = local path** `/opt/codestra/quarantine/agent-desktop-unapproved-20260725T233810Z` | `staging/sipjs-webrtc-20260726` | `4063a08` | **15** |
| `frontend` | `bitbucket.org/sip887/frontend` (token-auth URL) | `feature/codestra-customer-portal` | `c5e79af` | 0 (clean) |
| `vicidial-odoo-sync` | *(none configured)* | `rebuild/test-syn-odoo-import` | `0d3e837` | **3** |
| `odoo-addons` | `github.com/Codestra-SRL/codestra-odoo-addons` | `odoo19-middleware-security-role-20260804` | `fa32b9e` | **12** |
| `odoo19-vertical-addons` | *(none configured)* | `staging/vertical-suite-20260726` | `41801bf` | **2** |
| `contracts` | *(none configured)* | `contracts/v1` | `bf00a39` | **8** |
| `n8n-workflows` | `github.com/Codestra-SRL/codestra-n8n-workflows` | `feature/n8n-automation-blueprint` | `b39f26f` | **7** |
| `odoo19-call-center-addons` | *(none configured)* | `feature/phase1-foundation` | `41c8d3f` | **39** |
| `telephony-event-gateway-lifecycle-dev` | `github.com/Codestra-SRL/telephony-event-gateway` | `feature/telephony-lifecycle-contract-v1` | `d0ea394` | **12** |
| `automation` | *(none / no HEAD)* | — | — | 0 |
| `sip-provisioning` | *(none configured)* | `integration/durable-state-final` | `f558115` | **16** |
| `integration-tests` | *(none / no HEAD)* | — | — | 0 |

**Finding INV-P0-01** — **None of the 12 repos with a resolvable HEAD are on `main`/`master`.** All are on ad-hoc feature/staging/integration branches, and **10 of 12 have uncommitted local changes** (2–39 dirty files each; `odoo19-call-center-addons` alone has 39). This is the server-side half of the Step 2 "documented vs GitHub vs deployed vs runtime" reconciliation, and on its own it already proves: production-adjacent code running on this host is materially ahead of, behind, or divergent from whatever is committed/pushed to GitHub, for essentially the entire stack.
- Risk: **the actual behavior of the running system cannot be reconstructed from GitHub alone** — any incident response, rollback, or independent code review based on GitHub state will not match what's actually executing. This is the single most important finding of the entire audit's evidence-comparison mandate ("do not trust documentation by itself... compare DOCUMENTED vs GITHUB vs DEPLOYED vs RUNTIME").
- Recommended fix: for each repo, either (a) commit and push the working-tree changes to a reviewed branch and confirm which image/container was actually built from that state, or (b) `git stash`/discard if the changes are stale debugging artifacts — but this requires a human decision per repo, not an automated cleanup.
- Test required: for every "dirty" repo, `git diff` review to classify each change as (config drift / actual undeployed fix / debug leftover).
- Rollback requirement: N/A — do not touch working trees in Phase 1.
- GitHub repos: see table. Suggested branch per repo: `audit/reconcile-server-drift-<repo>-20260825`.

- **`agent-desktop`'s `origin` pointing to a local filesystem path inside `/opt/codestra/quarantine/agent-desktop-unapproved-20260725T233810Z`** (not GitHub) is independently notable: it means this checkout's "origin" is a quarantined, unapproved copy of itself, not the canonical GitHub remote. Flagged again in `03_GITHUB_RUNTIME_RECONCILIATION.md`.

## Python / Node environments

- Odoo processes run via system Python3 (`/usr/bin/python3 /usr/bin/odoo`) inside containers — addons paths span `/usr/lib/python3/dist-packages/odoo/addons`, `/mnt/r1-addons`, `/mnt/reviewed-addons`, `/mnt/extra-addons`, `/mnt/integration-addons`, `/mnt/call-center-addons` (multiple mount points per Odoo instance — full addon inventory in `04_ODOO_READINESS.md`).
- Middleware containers run a Python entrypoint pattern `python -m app.entrypoints.<name>` (e.g. `vicidial_adapter`) via a custom `live-delivery-admission` init wrapper — worth reviewing in `07_MIDDLEWARE.md` for what "admission" gating it performs.
- `.production-readiness-validation-venv` exists at `/opt/codestra/.production-readiness-validation-venv` — a dedicated Python venv for readiness validation tooling; correlates with the now-inert `codestra-readiness-*` timers (Finding INV-P2-04) — suggests a readiness-validation subsystem that was active as recently as ~3 weeks ago and has since gone quiet.

## Log locations

- `/opt/codestra/logs` (mode 750, owner `codestra-admin` group) — application logs.
- `/opt/codestra/deploy-logs` — deployment logs.
- `/opt/codestra/evidence` (mode 700) — 91 entries, appears to be structured evidence bundles from prior remediation/certification work (ties into `restore-validation/evidence`, see `17_BACKUP_DR.md`).
- Container logs via standard `docker logs` (json-file driver, not inspected for rotation policy — flag for `16_OBSERVABILITY.md`).
- `rsyslog.service` running at host level for system logs (`/var/log/*`).

## Summary counts for this file

P0: 1 · P1: 1 · P2: 4 · P3: 1
