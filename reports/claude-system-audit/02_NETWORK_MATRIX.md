# 02 — Network Dependency Matrix (codestra-app host)

Built from: `ss -tlnp` (actual listening sockets + owning process), `ufw status verbose`, `iptables -L -nv`, `docker network inspect`, `docker inspect --format .HostConfig.NetworkMode`, `/etc/hosts`, `~/.ssh/config`. All read-only.

## External / edge exposure (bound to the public IP or 0.0.0.0)

| SOURCE | DESTINATION | PORT | PROTO | TLS | AUTH | PURPOSE | PUBLIC/PRIVATE |
|---|---|---|---|---|---|---|---|
| Internet | `65.109.65.169` (host Caddy, systemd) | 80 | HTTP | redirects to 443 | n/a | ACME cert issuance + HTTP→HTTPS redirect | **PUBLIC** |
| Internet | `65.109.65.169` (host Caddy, systemd) | 443 | HTTPS | yes (Caddy-managed certs) | per-route (see `09_CADDY.md`) | Public edge for all externally-facing app routes | **PUBLIC** |
| Internet | `0.0.0.0:22` (sshd) | 22 | SSH | n/a (SSH) | key-based (per `fail2ban` sshd jail + presumed `PasswordAuthentication no`, verify in `15_SECURITY.md`) | Server administration | **PUBLIC** (expected, UFW-allowed, fail2ban-protected) |

No other service is bound to the public IP or `0.0.0.0` other than SSH and the host Caddy on 80/443. `ss -tlnp` confirms every other listener is on `127.0.0.1` or the private VLAN IP `10.40.0.1` — this is good hygiene for a Docker host (Docker's iptables manipulation is a common source of accidental public exposure, and it does not appear to have caused one here based on the socket-level evidence, though see Finding NET-P2-01 on UFW/Docker interaction below).

## Private VLAN (10.40.0.0/24) — the "mesh" between hosts

| SOURCE | DESTINATION | PORT | PROTO | TLS | AUTH | PURPOSE | PUBLIC/PRIVATE |
|---|---|---|---|---|---|---|---|
| `10.40.0.1` (this host) | `10.40.0.2` (codestra-vicidial) | 22 | SSH | n/a | ed25519 key, `BatchMode yes` | Ops/automation access to VICIdial host | PRIVATE |
| `10.40.0.1` (this host) | `10.40.0.4` (codestra-provider / telnexa+klyrow) | 22 | SSH | n/a | ed25519 key, `BatchMode yes` | Ops access (out of audit scope) | PRIVATE |
| `10.40.0.1` (this host) | `10.40.0.3` (codestra-scraper) | 22 | SSH (as **root**, not `codestra-admin`) | n/a | ed25519 key, `BatchMode yes` | Ops access (out of audit scope) | PRIVATE |
| `10.40.0.4` (provider/klyrow) | `10.40.0.1:8095` (this host, middleware main API) | 8095 | HTTP(S)? | unconfirmed — needs check against `07_MIDDLEWARE.md` | unconfirmed | UFW comment: **"Klyrow middleware private API"** | PRIVATE, but see Finding NET-P0-01 |
| `10.40.0.4` (provider/klyrow) | `10.40.0.1:18080` (this host, Caddy-hosted) | 18080 | HTTP(S)? | unconfirmed | unconfirmed | UFW comment: **"Klyrow to email provider event worker"** | PRIVATE, but see Finding NET-P0-01 |
| `10.40.0.2` (vicidial) | `10.40.0.1:443` | 443 | HTTPS | yes | unconfirmed | `codestra-private-vicidial-ingress-1` Caddy container listens here — likely the VICIdial↔middleware ingress path | PRIVATE |

**Finding NET-P0-01 — Cross-tenant/cross-product network path bypasses the Kong policy-enforcement boundary the mission's architecture explicitly mandates.**
- Observed evidence: `ufw status verbose` shows two explicit ALLOW rules: `10.40.0.1 8095/tcp on enp41s0.4001 ALLOW IN 10.40.0.4 # Klyrow middleware private API` and `10.40.0.1 18080/tcp on enp41s0.4001 ALLOW IN 10.40.0.4 # Klyrow to email provider event worker`. `10.40.0.4` is the `codestra-provider` host, which `/etc/hosts` maps to `telnexa.internal.codestra.agency` and `klyrow.internal.codestra.agency` — per the user's own scoping decision earlier in this audit, these are **separate products/businesses**, explicitly excluded from "the Codestra communications and contact-center platform" scope. Port 8095 is the Codestra **middleware's main API** (`codestra-middleware-1`), reachable here directly over the private VLAN, not through Kong (`127.0.0.1:8000-8002`, loopback-only) or the public Caddy edge.
- Expected state per mission's architectural authority: *"Odoo, browser clients, n8n, AI agents, and other applications must not bypass middleware and write directly into VICIdial administrative/database interfaces"* and *"Kong = API gateway and API policy enforcement."* By extension, a separate product/business reaching the middleware's main API directly over a raw VLAN firewall hole — with no Kong policy layer, rate limiting, or (as far as can be determined from this host alone) audited authentication in front of it — is the same category of boundary violation the mission is explicitly worried about, just at the network layer instead of the VICIdial-DB layer.
- Current state: firewall-permitted direct L3/L4 path exists and is presumably actively used (rule has a specific, intentional-sounding comment, not a leftover).
- Risk: **P0** — if 8095 does not itself enforce strong service-to-service auth (mTLS/JWT) independent of network position, a compromise of the separate Klyrow/Telnexa product (a different, less-audited codebase per the GitHub repo list) gains a direct path into Codestra's core middleware API, with no Kong-level policy, WAF, or rate-limiting in front of it. Even if 8095 does enforce auth, this path is invisible to Kong-based observability/rate-limiting/policy — an unmanaged side-door into the platform.
- Recommended fix: either (a) route this traffic through Kong (publish the relevant middleware routes via Kong with proper auth/rate-limit plugins, remove the direct UFW hole), or (b) if a private port is unavoidable, require mTLS on 8095/18080 and restrict to only the specific client cert for the provider integration, and document this exception explicitly as an approved architecture deviation — currently it appears to be an ungoverned firewall rule, not a documented exception.
- Test required: confirm what auth 8095 and 18080 actually enforce (`07_MIDDLEWARE.md`/`11_EMAIL.md` to verify); confirm whether Kong has any route at all for this traffic today.
- Rollback: N/A (Phase 1 finding only — no firewall changes made).
- GitHub repo: `codestra-production-platform` (firewall/network config) + middleware repo for the auth-on-8095 question. Suggested branch: `security/klyrow-middleware-access-review-20260825`.

## Docker bridge networks (container-to-container, per Compose project)

60 `docker network ls` entries (bridge driver, local scope), one per active/historical Compose project — e.g. `codestra_backend` (172.18.0.0/16, main stack), `codestra_edge` (172.19.0.0/16, edge-facing services incl. Kong, mail-isolated proxy, private-integration-gateway), `codestra-kong_kong_backend`, `codestra-identity_identity_service`, `codestra-n8n-staging_backend`/`_edge`, etc. Many (`br-21d379d1ba1c`, `br-55e9cd920f28`, `br-97ec7fa9e476`, `br-f7fe25a11770`, `br-5b748486f10b`, `br-e6acef04bd5a`, `br-70f87e442fb1`, `br-71fc15fedee5`, `br-3e04129c6182`, `br-062e418ad103`, `br-3efcb0146628`, `br-5b3a47f4904b`, `br-9f33f171c204`, `br-8afd4e09ea39`, `br-2a4c1e718cdb`, `br-077e220b4b75`, `br-17038819f019`) show `linkdown`/no active member interfaces — stale bridges from torn-down Compose projects that were never `docker network rm`'d.

**Finding NET-P3-01** — 17+ stale/orphaned Docker bridge networks left from decommissioned Compose projects.
- Risk: low (cosmetic/hygiene, minor kernel resource usage), but makes `docker network inspect`-based auditing noisy and error-prone for whoever audits this next.
- Recommended fix: `docker network prune` after confirming no stopped-but-not-removed containers still reference them.
- Repo: N/A (host hygiene). Suggested branch: `ops/docker-network-prune`.

## Notable network isolation container

`codestra-provisioning-service_telephony_private` and `codestra-provisioning-service_private` networks exist specifically for the provisioning service — naming suggests intentional isolation of telephony-adjacent secrets/config from the general backend network, which is good practice (verify actual member containers/no cross-links in a follow-up if `07_MIDDLEWARE.md`/`06_VICIDIAL_ASTERISK.md` need it).

## Public/private exposure cross-check summary

| Category | Count | Exposure |
|---|---|---|
| Bound to public IP or 0.0.0.0 | 2 (SSH, host Caddy 80/443) | Expected/PUBLIC |
| Bound to `10.40.0.1` (private VLAN only) | 4 (Caddy vicidial-ingress :443, middleware :8095, Caddy :18080, Caddy :80 internal) | PRIVATE, mesh-reachable |
| Bound to `127.0.0.1` only | ~25 (Kong 8000-8002, all internal Caddy proxy ports 18101-18116, mail ports, control-plane 8096, reseller-portal 18081, email-reseller 18180, staging middleware 31883, agent-desktop 31880/31881, uat-loopback-proxy 19069) | Host-local only, not reachable from other mesh hosts or the internet |

No evidence found of any database (Postgres/Redis), Kong admin API, or internal control-plane surface bound to a publicly-reachable address. The one confirmed cross-boundary exposure is the Klyrow/provider access documented in NET-P0-01.

## Summary counts for this file

P0: 1 · P1: 0 · P2: 0 · P3: 1
