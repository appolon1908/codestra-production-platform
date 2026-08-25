# 10 — Keycloak / Identity Audit

Scope: `codestra-identity-keycloak-1` (Up/healthy, ports 8080/8443/9000, not directly published to
the host — reached via Caddy at `auth.codestra.co`). Realm export reviewed at
`/opt/codestra/identity-platform/realms/codestra-realm.json`. Live OIDC discovery document
fetched read-only from `https://auth.codestra.co/realms/codestra/.well-known/openid-configuration`
(public endpoint, GET only) to confirm the realm export matches what's actually being served.

## Realm-level settings (from live discovery + realm export, consistent with each other)

- Issuer: `https://auth.codestra.co/realms/codestra` — confirmed live and matches the export.
- `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `device_authorization_endpoint` all
  present and resolve under the same issuer — no split-brain issuer URLs found.
- `accessTokenLifespan`: 300s (5 min) — reasonable.
- `ssoSessionIdleTimeout`: 1800s (30 min) / `ssoSessionMaxLifespan`: 28800s (8h) — reasonable for
  an agent-facing system with shift-length sessions.
- PKCE (`code_challenge_methods_supported`) is advertised by the discovery document.

## Client inventory (from realm export — 8 clients)

| Client | Type | standardFlow | PKCE | serviceAccounts | Assessment |
|---|---|---|---|---|---|
| `codestra-agent-desktop` | public | yes | **S256** | no | Correct for a browser SPA — no client secret to leak, PKCE required. |
| `codestra-agent-auth-gateway` | confidential | yes | **S256** | no | This is the oauth2-proxy sitting in front of `phone.`/`dialer.codestra.agency` (port 18113 in 09_CADDY.md). Confidential + PKCE + auth-code flow is the right shape for a server-side proxy. |
| `codestra-sip-provisioning` | confidential | no | — | no | No standard flow, no service account — likely uses a different grant (client-credentials implied by absence, but `serviceAccountsEnabled: false` means it can't actually do client-credentials either). **Flagged for follow-up**: if nothing is enabled, how does this client authenticate at all? Possibly unused/placeholder. |
| `codestra-odoo-agent-api` | confidential | no | — | no | Same shape/question as above — no enabled flow found in the export. |
| `codestra-middleware` | confidential | no | — | **yes** | Correct: machine-to-machine, client-credentials grant via service account. |
| `codestra-n8n` | confidential | no | — | **yes** | Correct, same pattern. |
| `codestra-reporting` | confidential | no | — | **yes** | Correct, same pattern. |
| `codestra-integration-test` | confidential | no | — | **yes** | Test/CI client — correct pattern, but worth confirming it's scoped down (roles/audience) so a leaked test credential can't reach production data. Not verified in this pass. |

No client has `implicitFlowEnabled: true` — good, no legacy implicit-flow exposure anywhere in the
realm.

## Findings

**IDENTITY-01 (P2) — Two confidential clients (`codestra-sip-provisioning`,
`codestra-odoo-agent-api`) have no OAuth grant type enabled in the realm export**
(`standardFlowEnabled: false`, `implicitFlowEnabled: false`, `serviceAccountsEnabled: false`,
`directAccessGrantsEnabled: false` — all four checked, all false). As exported, these clients
cannot obtain a token through any standard Keycloak flow. Either: (a) they're legacy/unused and
should be removed, (b) they authenticate via a non-standard mechanism not captured by this export
(e.g., a custom grant or the `codestra-gateway-identity` Kong plugin's secret-file scheme covers
them instead — see 08_KONG.md), or (c) the export is stale relative to the live Keycloak admin
config. Recommend checking live Keycloak admin state (not just the export file) for these two
clients specifically before deciding whether to remove or fix. Marked P2 rather than P1 because a
client with no usable grant is a "broken/dead" risk, not an "open" risk.

**IDENTITY-02 (informational — could not verify) — Live Keycloak Admin API state was not queried.**
Obtaining a read-only admin token would have required either using a service-account client secret
(the mission explicitly forbids exposing/using secrets) or an interactive admin login (not
available non-interactively). All findings above are therefore based on the **realm export file**
plus the **public OIDC discovery document**, not a live Admin API read. This means: client secret
rotation state, exact redirect-URI allow-lists, per-client fine-grained role mappings, and whether
the live realm has drifted from this export file are all **UNVERIFIED**. Recommend a follow-up
pass using a properly scoped read-only Keycloak admin credential (obtained through an authorized,
non-Claude-visible channel) if deeper live verification is required.

**IDENTITY-03 (P3) — Client secret storage paths (values not read):**
`/opt/codestra/secrets/identity-platform/keycloak.env`,
`/opt/codestra/secrets/identity-staging/middleware_client_secret`,
`/opt/codestra/secrets/identity-staging/keycloak.env`. All three live under `/opt/codestra/secrets`
which is `drwx------` (root-only) per the earlier filesystem inventory — appropriate permissions.
No production-vs-staging secret directory separation issue observed (they're in visibly different
`identity-platform` / `identity-staging` subdirectories). No action required; recorded for
completeness per the mission's "never print secret values, but record where they live" instruction.

## Redirect-URI / audience validation in relying-party code (spot-checked)

`mail_platform/api.py` independently validates both audience and issuer when decoding tokens
(`jwt.decode(raw, key.key, algorithms=["RS256","PS256"], audience=AUDIENCE, issuer=ISSUER)`),
using its own `PyJWKClient` against the live JWKS URI rather than trusting an upstream-injected
header blindly — this is the correct pattern and was independently confirmed by reading the
source, not just documentation (see 08_KONG.md KONG-01 for the related Kong-gateway-config gap on
this same service). Only one relying-party file was checked in this pass; recommend the same
audience+issuer check be confirmed present in the VICIdial adapter, Odoo integration modules, and
the SMS API (all referenced elsewhere in this audit) as a follow-up — **UNVERIFIED** for those.

## Not verified in this pass
- Live Keycloak Admin REST API state (see IDENTITY-02).
- Redirect-URI allow-lists per client.
- Role/group mappings and tenant/business-unit claim propagation into tokens.
- Whether `codestra-identity-staging-*` (the separate staging Keycloak instance, also
  Up/healthy) has meaningfully different — and correctly isolated — realm/client config from
  production. Only the production realm export was read.
- Logout/session-revocation behavior end-to-end (config values were read; actual revocation
  behavior was not exercised, per Phase 1 no-live-action constraints).

## GitHub repository
Realm export and gateway config live under `/opt/codestra/identity-platform/` — reconciliation
with the actual GitHub repo/branch of record is pending 03_GITHUB_RUNTIME_RECONCILIATION.md.
