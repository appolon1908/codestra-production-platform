# 06 — VICIdial & Asterisk (Steps 9–10)

**Scope:** `codestra-vicidial` host (10.40.0.2 / public 65.21.67.207), reached via read-only SSH (`ssh codestra-vicidial`, key auth, no sudo). Companion "main app" host (Odoo/middleware/Kong/Caddy) is covered in other report files, not here.

**Access constraints (read this first):** the `codestra-admin` account used has **no sudo** (`sudo: a password is required`) and is **not a member of** `asterisk`, `mysql`/`mariadb`, or `systemd-journal`. As a direct result: `/etc/asterisk/*`, `/etc/astguiclient.conf` (VICIdial's DB credential file), the VICIdial MySQL database itself, and the systemd journal for other units are all **permission-denied** from this account. Everything below marked `UNVERIFIED` is a genuine audit-coverage gap caused by this access boundary, not a claim that the item is broken.

---

## What's confirmed running (evidence)

- OS: openSUSE Leap 15.6, kernel 6.4.0-150600.23.103-default, uptime 8 days.
- Network: `eth0` has **public IP 65.21.67.207/26**; `eth0.4001` has private mesh IP `10.40.0.2/24`. This host is directly internet-facing, not just reachable over the private VLAN.
- `asterisk -V` → **Asterisk 18.26.4-vici** (VICIdial's Asterisk fork), process `root 1874 ... /usr/sbin/asterisk -fn`, running since Aug 16 (9 days).
- `mysql --version` → **MariaDB 10.11.15**, `mysqld` running, bound `127.0.0.1:3306` only (not publicly exposed — good).
- `vicidial.service` — `active (exited)`, oneshot bootstrap, completed successfully, enabled at boot.
- VICIdial web app present at `/srv/www/htdocs/vicidial` (admin) and `/srv/www/htdocs/agc` (agent interface) — this is a traditional bare-metal VICIdial install (Apache + PHP), **not containerized**, unlike the main app host. `apache2` config/apparmor profiles present; no nginx/caddy found on this host.
- AMI (`5038`) bound `127.0.0.1` only — correctly not exposed externally.
- A dedicated `codestra-ami-tls-proxy.service` wraps AMI in TLS via `socat` on `127.0.0.1:5040` (client cert at `/etc/asterisk/codestra-ami-tls/`) for the middleware integration path — good defense-in-depth design, consistent with the mission's "middleware is the only authorized writer" boundary.
- Narrow-scope adapter processes are present and running, matching the intended architecture (Odoo/n8n must not touch VICIdial directly):
  - `codestra-vicidial-adapter.service` — "Codestra passive VICIdial telephony event gateway"
  - `codestra-vicidial-restricted-adapter.service` — "Codestra restricted VICIdial read-only staging adapter" (uvicorn on `127.0.0.1:8097`)
  - `codestra-vicidial-observer.service` — "Codestra VICIdial Read-Only Observer" (PID 1881, python)
  - `codestra-telephony-provisioning-adapter.service`
  - Local health probes: `curl 127.0.0.1:8095/health` → `{"status":"ok"}`; `127.0.0.1:8097/health` → `{"status":"live"}`. Actual route surfaces beyond `/health` are undocumented from this vantage point — deeper API inventory belongs to the Middleware report (07), which should cross-reference these same processes from the source-code side.
- A public floating IP `65.21.67.207:5349` shows **20 duplicate `LISTEN` entries** — consistent with a TURN/TURNS relay (coturn) using `SO_REUSEPORT` worker processes for WebRTC media relay. Not inherently a problem, but flagged for the WebRTC report (05) to confirm ownership/config.

## What could NOT be verified (UNVERIFIED — access-limited, not "clean")

Campaigns, lists, user groups, VICIdial users, phones, inbound groups, closer groups, DIDs, remote agents, scripts, statuses/dispositions, callback config, recording retention policy, lead routing/hopper behavior, dial ratios, manual vs. automatic dialing config, time zones, call-time restrictions, and the VICIdial↔Odoo user/campaign/extension mapping comparison (Step 9 in full) are **all UNVERIFIED** — the DB credentials and VICIdial admin config are root/`asterisk`-group-only and not readable by the audit account. Full PJSIP/SIP dialplan, trunk, context, queue, conference, recording-path, CDR/CEL, and codec configuration (Step 10 in full) are similarly UNVERIFIED — `/etc/asterisk` is not readable.

**Do not treat the absence of findings here as "compliant."** This is the single largest coverage gap in the whole audit and should be called out explicitly in the executive summary and blockers list.

---

## Findings

### VIC-P0-01 — World-writable file inside the live, internet-served VICIdial agent web root
- **Severity:** P0
- **Component:** VICIdial agent web UI (Apache, `/srv/www/htdocs/agc/`)
- **Observed evidence:**
  ```
  -rwxrwxrwx root:root 63 /srv/www/htdocs/agc/vicidial_auth_entries.txt
  ```
  This directory is Apache's live document root for the agent web app (`vicidial.php`, `vicidial_redirect.php` live alongside it), and Apache is listening on `*:80` / `*:443` on a host with a public IP (65.21.67.207). No reverse proxy/WAF was found in front of Apache on this host.
- **Expected state:** Files inside a public web root should never be world-writable, and any auth-related artifact should be outside the document root or access-restricted (`.htaccess`/deny-all).
- **Current state:** `chmod 777`, owned by `root`, filename strongly suggests it holds agent authentication/session state, sitting in a directory reachable over the public internet.
- **Risk:** Integrity risk (any local process, however unprivileged, can overwrite an auth-related file used by the live agent login flow) and possible confidentiality risk if the file is directly HTTP-fetchable and contains live credentials/session tokens — **content was not read** (redaction/least-invasive policy), so exact sensitivity is unconfirmed and must be checked with root access.
- **Files:** `/srv/www/htdocs/agc/vicidial_auth_entries.txt` on `codestra-vicidial` (10.40.0.2 / 65.21.67.207)
- **Recommended fix:** With root access, (1) inspect file contents to classify sensitivity, (2) fix permissions to the minimum needed (typically `www`-group writable only, not world), (3) confirm via Apache config whether `.txt` files under `agc/` are directly servable and if so deny them, (4) check `git log`/deploy history for why this ended up world-writable — likely a `chmod -R 777` during a past install/fix.
- **Test required:** After remediation, attempt `curl https://<host>/agc/vicidial_auth_entries.txt` from outside and confirm it 403s or 404s; confirm agent login still functions.
- **Rollback:** Trivial (`chmod` revert) — low risk to fix.
- **GitHub repo:** not applicable (server-local file, not tracked in a repo as far as this fork could determine).
- **Suggested branch:** `fix/vicidial-agc-webroot-permissions`

### AST-P0-02 — Asterisk's built-in HTTP server bound to all interfaces on a publicly-addressed host
- **Severity:** P0
- **Component:** Asterisk `res_http_websocket`/`mod_http` management HTTP server
- **Observed evidence:**
  ```
  LISTEN 0 10 0.0.0.0:8089 0.0.0.0:*
  LISTEN 0 10 0.0.0.0:8088 0.0.0.0:*
  ```
  plus `ip -brief addr` confirming a public IP is bound directly to this host's `eth0` (no NAT/firewall host in front observed). Probing `http://127.0.0.1:8088/` and `:8089/`, and the common paths `/ari/asterisk/info` and `/httpstatus`, all returned generic Asterisk 404s — meaning **something** is listening and answering with Asterisk's own HTTP stack, but the exact enabled sub-handlers (ARI, AMI-over-HTTP, static file server, websocket) could not be enumerated because `/etc/asterisk/http.conf` is not readable by this account.
- **Expected state:** Per the mission's own Step 10 requirement ("Determine whether Asterisk exposes unnecessary public management interfaces"), Asterisk's HTTP management server should be bound to `127.0.0.1` (or a private-VLAN address) and reached only via the middleware adapter/reverse proxy — never `0.0.0.0` on a box that also carries a public IP.
- **Current state:** Bound to `0.0.0.0`, which — combined with the public IP on `eth0` and no on-host reverse proxy — means this surface is reachable directly from the internet.
- **Risk:** Depending on what's actually enabled in `http.conf` (unknown from here), this ranges from low (only WebSocket for the softphone, properly authenticated) to severe (ARI or AMI-over-HTTP reachable pre-auth). This inconsistency is notable given AMI itself (raw `5038`) **is** correctly loopback-only — the hardening applied to one Asterisk management channel wasn't applied to the other.
- **Files:** `/etc/asterisk/http.conf` (UNVERIFIED contents — root required)
- **Recommended fix:** With root access, read `http.conf`, confirm exactly what's enabled; if this is intentionally the WebRTC softphone WebSocket endpoint, restrict `bindaddr` to the private VLAN IP (`10.40.0.2`) and require callers to go through a TLS-terminating reverse proxy (Caddy) the way the main app host does, not raw Asterisk HTTP on a public IP.
- **Test required:** From outside the private mesh, confirm `8088`/`8089` are no longer reachable after the fix; confirm WebRTC agent phone still connects.
- **Rollback:** Revert `bindaddr` change and restart Asterisk (service restart is a Phase 2 action, not Phase 1).
- **Suggested branch:** `fix/asterisk-http-bind-scope`

### VIC-P1-03 — Three health-check systemd units for the Asterisk/VICIdial integration path are actively failing
- **Severity:** P1
- **Component:** Observability / health monitoring for telephony integration
- **Observed evidence:**
  ```
  codestra-asterisk-health.service              failed (Result: exit-code)
  codestra-integration-health.service           failed (Result: exit-code)
  codestra-vicidial-restricted-adapter-health.service  failed (Result: exit-code), status=2
  ```
  All three are timer-triggered and re-fail on every tick (observed re-failing within the ~15-minute audit window). `journalctl` for the actual failure reason is UNVERIFIED (no journal access as `codestra-admin`).
- **Expected state:** Per Step 20 (Observability), the telephony integration path needs a working health signal; per the mission's overall goal ("determine what actually works"), a broken health check on this specific path is a direct blocker to trusting any "it's healthy" claim elsewhere in this audit about VICIdial↔middleware connectivity.
- **Current state:** All three broken, meaning nobody is currently getting a reliable automated signal if Asterisk or the VICIdial↔middleware integration actually goes down.
- **Risk:** Silent failure risk — an outage in the telephony path could go undetected until agents/customers notice.
- **Recommended fix:** Root-level investigation of `/usr/local/sbin/codestra-asterisk-health`, `/usr/local/sbin/codestra-integration-health`, and `/opt/codestra/vicidial-restricted-adapter/current/scripts/read_only_probe.py` exit codes/journal output; likely candidates are a changed credential path (`/run/credentials/...` — note the restricted-adapter probe explicitly takes an `adapter-hmac` credential file argument, so a credential rotation or systemd `LoadCredential` misconfig is a plausible root cause) or an API contract change on the adapter side.
- **Test required:** After fix, confirm all three units report `active` after their next timer fire, not just once.
- **Suggested branch:** `fix/vicidial-integration-health-checks`

### VIC-P1-04 — Step 9/10 deep configuration audit is UNVERIFIED due to audit-account access scope
- **Severity:** P1 (coverage gap, treat as a blocker to declaring PRODUCTION_READY on telephony specifically)
- **Component:** Audit process / access model
- **Observed evidence:** No sudo, not in `asterisk`/`mysql`/`systemd-journal` groups (see access constraints above).
- **Expected state:** The mission requires a full read-only inventory of campaigns, lists, DIDs, users, dial ratios, recording retention, etc.
- **Current state:** None of that is verifiable from this account.
- **Recommended fix:** Do **not** simply grant the general audit account root/DB access — that would violate the same least-privilege posture this audit is supposed to be checking for. Instead: (a) query VICIdial state through the existing authenticated `vicidial_adapter`/`restricted-adapter` read APIs on `127.0.0.1:8095`/`8097` (their `/health` responds; full route inventory needed from the Middleware report), or (b) have a human with legitimate VICIdial admin access run a scoped read-only export for a future audit pass.
- **Suggested branch:** n/a — process recommendation, not a code fix.

### VIC-P2-05 — `codestra-vicidial-observer.service` description says "inactive candidate" but it's been actively running for 1+ week
- **Severity:** P2
- **Component:** Config/state hygiene
- **Observed evidence:** `systemctl status` shows `Codestra VICIdial Read-Only Observer (inactive candidate)` as the unit description while `Active: active (running) since Sun 2026-08-16 ... 1 week 1 day ago`.
- **Risk:** Low direct risk (it's read-only per its own name), but the label/state mismatch suggests this component was promoted from staging/candidate to continuously-running without updating its own description — a signal worth tracing in GitHub history (report 03) to confirm the promotion was deliberate and reviewed.
- **Recommended fix:** Update the unit description to match reality, or investigate whether this should still be time-limited/candidate-only.
- **Suggested branch:** `chore/vicidial-observer-unit-description`

### AST-P3-06 — No reverse proxy in front of VICIdial's Apache stack (architectural inconsistency)
- **Severity:** P3
- **Component:** Edge/TLS architecture
- **Observed evidence:** Apache serves the agent/admin web UI directly on `*:80`/`*:443` of a publicly-addressed host; no Caddy/nginx found here, unlike the main app host where Caddy fronts everything.
- **Recommended fix:** Not urgent, but worth normalizing — e.g. terminate TLS via the same hardened Caddy image used elsewhere in the fleet and reverse-proxy to Apache on loopback, for consistent security-header/TLS policy and centralized cert management.
- **Suggested branch:** `feature/vicidial-caddy-front`

---

## Summary for this report

- **VICIdial/Asterisk are real, actively running production services** (Asterisk 18.26.4-vici up 9 days, VICIdial's traditional Apache+PHP web app present, MariaDB backing it) — this is **not** scaffolding or empty test data as far as process/service evidence goes. However, the deep configuration content (campaigns, users, DIDs, dial settings) could not be confirmed either way from this account, so "is it production-configured with real campaigns" remains **UNVERIFIED**, not confirmed positive.
- The architecture correctly uses narrow read-only/passive adapters rather than direct DB access from Odoo/n8n — matches the mission's intended boundary.
- The most important security finding is the pair of **P0s**: a world-writable auth-named file sitting in the public web root (VIC-P0-01), and Asterisk's HTTP management server bound to all interfaces on a publicly-addressed host with unknown enabled sub-handlers (AST-P0-02).
