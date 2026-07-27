# Keycloak public DNS and TLS remediation

Result: `PASS`

## DNS

Independent public queries to Cloudflare (`1.1.1.1`) and Google (`8.8.8.8`)
both returned `65.109.65.169` for `auth.codestra.agency`. No `/etc/hosts`
result was used as evidence.

## Pre-change finding

The active Compose-managed reverse proxy was
`codestra-reverse-proxy-1`, image
`codestra/caddy:2.11.4-hardened-20260723`. The inactive host-level Caddy
service was not used.

The live Caddyfile explicitly selected `tls internal` for the public Keycloak
hostname. The externally served certificate was issued by `Caddy Local
Authority - ECC Intermediate`, covered only `auth.codestra.agency`, and
expired on July 28, 2026.

Protected backup:

`/opt/codestra/backups/keycloak-tls-20260727T221840Z`

It contains the pre-change Caddyfile, Compose definition, local certificate
metadata, certificate, and key. The directory is mode `0700`.

## Remediation and validation

The `tls internal` directive was removed from the public site. Both the
containerized Caddy configuration and Compose model passed validation before
restarting only the Compose reverse-proxy service.

Caddy completed an HTTP-01 ACME challenge and obtained the public certificate.
External verification returned:

- Subject: `CN=auth.codestra.agency`
- Issuer: `C=US, O=Let's Encrypt, CN=YE2`
- notBefore: `2026-07-27 21:20:38 UTC`
- notAfter: `2026-10-25 21:20:37 UTC`
- SAN: `DNS:auth.codestra.agency`
- SHA-256 fingerprint:
  `C1:5A:92:EB:2A:03:DB:7E:82:E1:20:F3:46:1A:BA:62:78:19:4C:4C:46:47:0E:62:EB:74:D7:8D:62:5B:1E:3E`
- Chain: leaf → Let's Encrypt YE2 → Root YE → ISRG Root X2
- HTTPS verification: OpenSSL trust succeeded and the Keycloak discovery
  endpoint returned HTTP 200 with curl verification result `0`.

The renewal owner and mechanism are the running Compose Caddy container using
its persistent `codestra_caddy_data` volume and automatic ACME renewal. The
container health status is `healthy`.

No Keycloak realm, user, client, database, or application state was mutated.
