# TLS and mTLS certificate lifecycle

Inventory verified on 2026-08-15. Certificate metadata is safe to record; private keys are never displayed, copied to evidence, or committed. Middleware Platform Operations owns every local renewal and reload below. The external DNS/ACME account owner is Codestra Infrastructure.

## Public TLS inventory

All public names terminate at `codestra-reverse-proxy-1` (Caddy 2.11.4). Each certificate has a single DNS SAN equal to its subject CN, is issued by Let's Encrypt, and is stored in the persistent `codestra_caddy_data` volume. Caddy's managed-certificate maintenance performs ACME renewal and swaps the renewed certificate in its live cache without a container restart.

| Subject / SAN | Issuer | Expiry (UTC) | Service | Renewal | Reload | Owner |
|---|---|---|---|---|---|---|
| `api.codestra.agency` | Let's Encrypt YE1 | 2026-10-18 17:15:36 | Middleware API | Caddy ACME | Caddy live cache | Middleware Platform Operations |
| `auth.codestra.agency` | Let's Encrypt YE2 | 2026-10-25 21:20:37 | Keycloak | Caddy ACME | Caddy live cache | Identity Operations / Middleware Platform Operations |
| `crm.codestra.agency` | Let's Encrypt YE2 | 2026-10-18 17:15:36 | Odoo | Caddy ACME | Caddy live cache | Middleware Platform Operations |
| `n8n.codestra.agency` | Let's Encrypt YE1 | 2026-10-18 17:15:36 | n8n production | Caddy ACME | Caddy live cache | Automation Operations / Middleware Platform Operations |
| `n8n-staging.codestra.agency` | Let's Encrypt YE2 | 2026-10-19 17:37:24 | n8n staging | Caddy ACME | Caddy live cache | Middleware Platform Operations |
| `bridge-staging.codestra.agency` | Let's Encrypt YE2 | 2026-10-19 21:27:13 | Middleware staging bridge | Caddy ACME | Caddy live cache | Middleware Platform Operations |
| `phone.codestra.agency` | Let's Encrypt YE2 | 2026-10-18 18:29:21 | Agent desktop | Caddy ACME | Caddy live cache | Telephony / Middleware Platform Operations |
| `monitoring.codestra.co` | Let's Encrypt YE2 | 2026-10-22 19:28:30 | Monitoring receiver | Caddy ACME | Caddy live cache | Middleware Platform Operations |

The six-hour `public-tls-monitor.timer` independently retrieves every public leaf, checks hostname matching, and alerts at 21 days. A safe renewal test consists of `caddy validate`, confirming the Caddy log reports certificate maintenance enabled, and running `public-tls-monitor.service`; Caddy has no certbot-style `--dry-run`. Do not force a production ACME order merely to create test evidence.

## Private CA and mTLS inventory

| Subject / SAN | Issuer | Expiry (UTC) | Service | Renewal | Reload | Owner |
|---|---|---|---|---|---|---|
| Private Integration Root CA R1 (CA, no SAN) | self-signed | 2036-07-19 17:08:52 | Middleware↔VICIdial trust | approved CA overlap only | trust bundles, then dependent services | Security PKI / Middleware Platform Operations |
| `middleware.internal.codestra.agency`; DNS SAN same | Private Integration Root CA R1 | 2027-08-23 21:14:46 | private middleware ingress | daily leaf timer, 30-day window | restart public and private Caddy containers | Middleware Platform Operations |
| `middleware-staging.internal.codestra.agency`; DNS SAN same | Private Integration Root CA R1 | 2027-01-20 00:43:16 | staging private ingress | daily leaf timer, 30-day window | restart public Caddy container | Middleware Platform Operations |
| `codestra-middleware-client-r1-20260722-130602`; SPIFFE `spiffe://codestra/internal/middleware/r1-20260722-130602` | Private Integration Root CA R1 | 2027-08-23 17:08:53 | middleware client to VICIdial adapter | daily leaf timer, 30-day window | restart listed middleware clients | Middleware Platform Operations |
| Internal Integration CA (CA, no SAN) | self-signed | 2031-08-09 05:56:07 | n8n/Odoo internal integration trust | approved CA overlap only | trust bundles, then dependent services | Security PKI / Middleware Platform Operations |
| `codestra-middleware-production`; SPIFFE `spiffe://codestra.internal/middleware/production` | Internal Integration CA | 2027-09-11 05:56:08 | internal middleware client | daily leaf timer, 30-day window | restart integration API | Middleware Platform Operations |
| `n8n.internal.codestra.agency`; DNS SANs n8n and odoo internal | Internal Integration CA | 2027-09-11 05:56:07 | internal integration proxy | daily leaf timer, 30-day window | configured consumer reload target | Middleware Platform Operations |
| Codestra Provisioning Staging CA (CA, no SAN) | self-signed | **2026-08-25 01:58:21** | staging provisioning trust | **monitor only; approved overlap rotation required** | provisioning service and clients | Security PKI / Middleware Platform Operations |
| `provisioning-service`; DNS service aliases, localhost, IP `127.0.0.1` | Provisioning Staging CA | **2026-08-25 01:58:21** | staging provisioning HTTPS | blocked by CA expiry; rotate with CA overlap | restart provisioning service | Middleware Platform Operations |

The VICIdial adapter server leaf (`authorization.internal.codestra.agency` / `edge.internal.codestra.agency`, expiry 2027-08-23) and peer client identities are owned and renewed on the VICIdial host. Middleware Operations owns the trust bundle and validation here; Telephony Operations owns peer issuance and reload.

## Private leaf issuance and renewal

The authoritative profiles are in `operations/tls/certificates.tsv`. `renew-private-certificate` generates a new 3072-bit key and CSR in a mode-0700 runtime directory, signs only with the existing CA, validates chain, expiry, SAN profile, and key match, then exits without exposing key material. `--dry-run --force` performs the complete issuance validation but changes nothing.

During a real renewal it retains the old pair in a mode-0700 `.overlap-<name>-<timestamp>` directory, installs the new pair, and restarts only the manifest's consumers. Keep the overlap copy until both sides have authenticated successfully across the maximum connection lifetime. Roll back by restoring that pair and restarting the same consumers. Never delete or replace a CA as part of leaf renewal.

## Private CA rotation

CA rotation requires Security PKI approval and a two-trust-window rollout:

1. Create the successor CA offline and record fingerprints and authorization; do not overwrite the current CA.
2. Distribute a bundle containing old and new roots to every verifier, then reload and prove old identities still work.
3. Issue new leaves from the successor CA, deploy clients and servers in bounded groups, and prove mutual authentication after each group.
4. Retain both roots for at least the longest connection/session lifetime plus rollback window.
5. Remove the old root only after inventory shows no old leaf in use and revocation/rollback evidence is complete.

The provisioning staging CA is already inside the 30-day critical window. Its leaf cannot be made safe by ordinary renewal because the issuer expires at the same time. It remains a documented escalation, not an implicit CA replacement.

## Monitoring

`codestra-certificate-renewal.timer` runs daily. It renews eligible leaves at 30 days, publishes `codestra_certificate_expiry_seconds` and `codestra_certificate_expiry_status` through node-exporter, then checks all public endpoints. Prometheus rules warn on private leaves at 30 days and page at 14 days; CA expiry pages at 30 days. Threshold breaches are logged while Prometheus owns notification; automation or endpoint-check failure invokes `tls-alert@.service` and writes to the system journal and lifecycle alert log.
