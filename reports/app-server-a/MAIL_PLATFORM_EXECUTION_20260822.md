# Mail platform execution record — 2026-08-22

## Safety boundary

- No email was submitted.
- No customer identity was created or modified.
- No public DNS record was changed.
- No unassigned production domain was activated.
- `mail.test` is reserved for the isolated `TEST_SYN` registry only.

## Authoritative ownership inventory

Production Odoo contained zero `call.center.campaign` records and the middleware
control-plane contained zero campaign records. Consequently, no exact COD, MBL,
Nativo, or Breero campaign authority could be selected. The approval matrix keeps
all human-mail domains blocked. `codestra.cloud` remains `SERVICE_ONLY`.

Result: `DOMAINS_ASSIGNED=0`, `DOMAINS_SYSTEM_ONLY=5`, `DOMAINS_BLOCKED=9`.

## DNS observation

`_dmarc.codestra.co` returned two policies:

1. `v=DMARC1; p=none;`
2. `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net;`

The reviewed change candidate is documented in `MAIL_DNS_CHANGESET_20260822.csv`.
It is deliberately not applied. Human outbound mail for `codestra.co` remains
disabled until the two records are replaced by one reviewed record and live DNS
is re-queried.

## Keycloak and synthetic registry

The seven mail realm roles exist in the canonical `codestra` realm. Effective
role mapping was verified for three synthetic identities:

- agent: `codestra_mail_user`, `codestra_mail_agent`
- standalone: `codestra_mail_user`
- supervisor: `codestra_mail_user`, `codestra_mail_supervisor`

Credentials are stored outside Git under `/etc/codestra/secrets/mail-platform/`.
The isolated registry has three users (one Odoo-linked, two without an Odoo
account) and one shared inbox with three members. Reconciliation returned no
registry drift.

## Verification

- Registry/RBAC/domain/threading/idempotency tests: 12 passed.
- App-password material: random, scrypt-hashed, returned once, revocable.
- Secret scan of `mail_platform`: no leaks.
- Trivy scoped scan: no secret findings; no dependency/config target was present.
- Stalwart 0.16.18 isolated restart: healthy; readiness endpoint returned 200.
- No SMTP, IMAP, JMAP, OIDC, webmail, Kong, n8n, Odoo inbox, or Klyrow runtime
  certification is claimed because Stalwart remains in bootstrap mode.

## Backup and restore

Backup: `/opt/codestra/mail-platform-backup-20260822-WkDdi6`

Isolated restore: `/opt/codestra/mail-platform-restore-20260822-B9q6Gl`

All three backup artifacts passed SHA-256 verification. Restored registry
`PRAGMA integrity_check` returned `ok`, with 1 domain, 3 users, 1 shared inbox,
and 3 memberships. Stalwart configuration and data archives extracted cleanly.

## Open gates

1. Owner must select exact campaigns and approve the domain matrix.
2. DNS administrator must review/apply the DMARC and mail-host changeset.
3. Stalwart must exit bootstrap mode and receive canonical Keycloak OIDC,
   mailbox objects, TLS, and protocol listener configuration.
4. Kong routes, n8n workflows, Odoo workspace, and Klyrow event bridge require
   isolated runtime deployment and negative/canary certification.
5. A protected PR and independent approval are required before merge.
