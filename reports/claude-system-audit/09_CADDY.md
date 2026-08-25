# 09 — Caddy Edge/TLS Audit

## Architecture — important, non-obvious finding

There is **not one Caddy instance** — there are at least six:

1. **systemd `caddy.service`** (`/etc/caddy/Caddyfile`, PID via systemd, not a container) — this
   is the actual public edge. `default_bind 65.109.65.169 127.0.0.1` — binds both the public IP
   and loopback. `admin unix//run/caddy/admin.sock` (Unix socket, not TCP — good, no admin API
   exposed on any network interface). `skip_install_trust` set (doesn't try to install a local CA
   trust store — appropriate for a server).
2. **`codestra-caddy-upstream-gateway`** container — a *separate* Caddy whose entire config
   (`/opt/codestra/caddy-upstream-gateway/Caddyfile`) is 16 bare `:181xx { }` blocks on
   `127.0.0.1` only, no hostnames. This is an internal fan-out layer the systemd Caddy reverse-proxies
   into (e.g. `phone.codestra.agency` → `127.0.0.1:18113/18114`), not a second public edge.
3. **`codestra-n8n-internal-proxy`**, **`codestra-odoo-internal-proxy`**,
   **`codestra-odoo19-module-staging-callback-tls-1`**, **`codestra-private-vicidial-ingress-1`**
   — each a small dedicated Caddy sidecar (image `codestra/caddy:2.11.4-hardened-20260723`) in
   front of one backend. `codestra-private-vicidial-ingress-1` binds `10.40.0.1:443` (the private
   mesh VLAN address) — **not** the public IP, which is the correct posture for VICIdial-facing
   traffic. Its own config was not independently pulled apart in this pass; recommend a follow-up
   pass specifically confirming it never binds `65.109.65.169`.

Do not evaluate "Caddy" as a single artifact in future audits — always specify which of the six.

## systemd Caddy — live hostnames (from `/etc/caddy/sites/*.caddy`, confirmed loaded via
`import sites/*.caddy` and validated non-destructively with
`caddy validate --config /etc/caddy/Caddyfile` inside the upstream-gateway container equivalent —
**Valid configuration**, no reload performed):

`api.breero.com`, `api.codestra.agency`, `crm.codestra.agency`, `n8n.codestra.agency`,
`n8n-staging.codestra.agency`, `api.staging.internal.codestra.agency`,
`n8n.staging.internal.codestra.agency`, `auth.staging.internal.codestra.agency`,
`odoo.staging.internal.codestra.agency`, `bridge-staging.codestra.agency`,
`middleware.internal.codestra.agency`, `middleware-staging.internal.codestra.agency`,
`phone.codestra.agency`, `dialer.codestra.agency`, `monitoring.codestra.co`, `api.codestra.co`,
`auth.codestra.co` (separate file), plus one non-hostname listener
`https://middleware-email-events.internal.codestra.agency:18080`.

A stale file `sites/current-production.caddy.before-canonical-auth-20260823T022311Z` exists but is
**correctly excluded** (doesn't match the `*.caddy` glob) — confirmed not live. Good hygiene.

## Findings

**CADDY-01 (P1) — `phone.codestra.agency` (agent-desktop *preview*) serves its app UI with no
auth gate; `dialer.codestra.agency` (the equivalent production block, same backend port 18114)
requires OAuth2 session on every path except `/oauth2/*`.**
Evidence — `dialer.codestra.agency` block:
```
@dialer_protected { not path /oauth2/* }
forward_auth @dialer_protected 127.0.0.1:18113 {
    uri /oauth2/auth
    ...
    handle_response @unauthenticated { redir * /oauth2/sign_in?... 302 }
}
```
`phone.codestra.agency` has **no equivalent blanket `forward_auth`**. Its `/realtime-api/*` path is
individually wrapped in `forward_auth`, but the catch-all `handle { reverse_proxy 127.0.0.1:18114 }`
(the actual app bundle / UI) and `/webphone-api/*`, `/ws/agent` are not — they reverse-proxy
directly. Both hostnames are bound to the public IP (`default_bind 65.109.65.169 127.0.0.1` with no
per-site override seen). This means the "preview" build of the agent desktop — which per its own
CSP still connects to `wss://wss.codestra.agency:8089` and `wss://api.codestra.agency`, i.e. real
backend infrastructure, not a sandbox — is reachable by anyone on the internet without
authentication, while its production sibling is properly locked down. Not confirmed whether the
app itself independently enforces login (would mitigate to P2/P3) — recommend checking
`codestra-agent-desktop-preview`'s own auth handling as a priority follow-up; if it has none, this
is a real unauthenticated-access path into agent tooling.
Files: `/etc/caddy/sites/current-production.caddy` (`# BEGIN CODESTRA_AGENT_DESKTOP_PREVIEW` /
`# BEGIN CODESTRA_AGENT_DESKTOP_DIALER` sections). Fix: add the same `forward_auth
@protected 127.0.0.1:18113` gate used on `dialer.codestra.agency` to `phone.codestra.agency`, or
confirm+document that "preview" is intentionally an internal/no-auth surface and firewall it off
the public IP instead. Test required: unauthenticated `curl https://phone.codestra.agency/`
should redirect to sign-in after the fix, matching `dialer.codestra.agency` behavior today.
Rollback: revert the added `forward_auth` block. Suggested branch: `fix/phone-preview-auth-gate`.

**CADDY-02 (P2, unresolved) — `api.breero.com` and presumably its upstream returned 503 on both
`/health` and `/api/v1` during this read-only test** (see 08_KONG.md KONG-02 for full detail — Caddy
here correctly proxies to Kong on 127.0.0.1:8000 per its own config; the 503 originates further
downstream). Caddy's config for this site is otherwise sound (security headers present, 10MB body
cap, explicit comment recording that auth is intentionally left to the Breero app). No Caddy-side
fix needed; tracked here because it was discovered via this site block.

**CADDY-03 (P3) — Basic-auth credential file present (`/etc/caddy/secrets/phone-auth.htpasswd`)
but not referenced by any currently-loaded site block** (grep found no `basicauth` directive
citing this file in `sites/*.caddy`, `snippets/*.caddy`, or `conf.d/*.caddy`). Either dead
leftover from a prior auth scheme (before the OAuth2 forward_auth pattern was adopted) or wired in
via a file not reviewed in this pass. Recommend confirming and removing if unused — an unused
credential file with real password hashes sitting in a security-sensitive directory is exactly the
kind of stale artifact worth cleaning up. Not rated higher because it is inert as configured.

**CADDY-04 (positive finding, no action needed) — Consistent security header baseline.** The
shared `(security_headers)` snippet (HSTS, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, restrictive
`Permissions-Policy`) is applied via `import security_headers` on `api.breero.com`, and
`phone.codestra.agency`/`dialer.codestra.agency` each hand-roll an equivalent (plus a real CSP with
`object-src 'none'; frame-ancestors 'none'`). Access-token response headers are explicitly redacted
in the log format (`resp_headers>X-Auth-Request-Access-Token replace REDACTED`) — good practice,
worth replicating on any other site block that proxies through the oauth2-proxy pattern.
Not verified: whether every one of the 17 hostnames applies the shared snippet consistently
(only `api.breero.com`, `phone.codestra.agency`, `dialer.codestra.agency` were read in full in this
pass) — recommend a follow-up sweep of the remaining 14 blocks (`crm.`, `n8n.`, `middleware.`,
`monitoring.`, `api.codestra.co`, `auth.codestra.co`, and the `*.staging.internal.*` set) for the
same headers, and confirming none of them serve plain HTTP without a redirect.

## Not verified in this pass
- The 4 dedicated Caddy sidecar containers (`n8n-internal-proxy`, `odoo-internal-proxy`,
  `odoo19-module-staging-callback-tls-1`, `private-vicidial-ingress-1`) each have their own
  Caddyfile that was not individually pulled and reviewed — only confirmed their port bindings
  from `docker ps`. `private-vicidial-ingress-1` binding to `10.40.0.1:443` only (not the public
  IP) is a good sign from `docker ps` output but its actual site-block content (host allow-list,
  auth) is **UNVERIFIED**.
- 14 of 17 systemd-Caddy hostnames not read in full (see CADDY-04).
- TLS certificate source/expiry (internal CA vs provided cert — `automatic HTTPS...disabled`
  confirms Caddy isn't doing its own ACME, but where the certs actually come from and their
  expiry was not traced in this pass).

## GitHub repository
Config lives at `/opt/codestra/config/caddy/` (repo-tracked, per the many `Caddyfile.pre-*`/
`Caddyfile.before-*` historical snapshots) and `/etc/caddy/` (deployed copy) — reconciliation
between the two, and which GitHub repo/branch owns them, is pending
03_GITHUB_RUNTIME_RECONCILIATION.md.
