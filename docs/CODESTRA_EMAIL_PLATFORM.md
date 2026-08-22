# Codestra Email Platform

## Authority and separation

The middleware `mail_platform` registry is authoritative for domains, campaign
ownership, mail users, aliases, shared membership, messages, audit, and
reconciliation. Keycloak at `https://auth.codestra.co/realms/codestra`
authenticates humans. Odoo is an optional CRM projection. Stalwart owns human
mailbox semantics. Klyrow/Postal remains the transactional/system delivery and
event plane. Kong is the API boundary and n8n only consumes or orchestrates
events.

No password is copied between Keycloak, Odoo, and Stalwart. OIDC/OAUTHBEARER is
preferred. Because common desktop mail clients have incomplete third-party
OAUTHBEARER support, an app-password fallback may be provisioned as a distinct,
random, revocable secret stored outside Git.

## Fail-closed rules

- A domain has one row and at most one campaign authority.
- Unassigned human-mail domains remain inactive and cannot provision users.
- Inbound campaign selection uses the recipient mailbox/domain only.
- Outbound authorization validates subject, active mailbox, From ownership or
  alias, domain, campaign, suppression, and role at the middleware and SMTP
  submission layers.
- Admin cross-domain use requires `mail.domain.override`, an explicit reason,
  and an immutable audit record.
- Suspension disables Keycloak/mail sessions and submission but preserves mail.
- Campaign transfer revokes old send authority before granting the new domain;
  historical messages retain their original domain and campaign.

## Provisioning saga

`mail.user.requested` creates or resolves the Keycloak subject, creates the
canonical `mail_user`, provisions the same UUID into Stalwart, and optionally
links an Odoo user. Every step is idempotent and compensating rollback disables
newly created access without deleting mailbox history. n8n receives
`MailUserProvisionedV1` only after middleware read-back succeeds.

## Deployment gate

The isolated Stalwart deployment uses `mail.test`, loopback-only host ports,
manual DNS, and no external recipients. Production promotion requires approved
domain/campaign rows, valid TLS, one DMARC record per domain, verified SPF/DKIM,
backup/restore, Keycloak OIDC configuration, protocol tests, and signed review.
