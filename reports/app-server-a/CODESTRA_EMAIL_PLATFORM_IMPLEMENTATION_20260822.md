# Codestra Email Platform — controlled implementation checkpoint

## Outcome

The canonical registry/policy foundation is implemented and tested. A pinned
Stalwart `v0.16` (`0.16.18` observed) mailbox engine is deployed in an isolated,
loopback-only bootstrap environment. No production DNS, customer mailbox,
campaign, Odoo account, Keycloak user, or external email was changed or sent.

## Implemented

- SQLite reference migration for domains, users, aliases, shared mailboxes,
  messages, audit, and reconciliation.
- Nullable and unique `odoo_user_id`, with in-place standalone-to-Odoo linking.
- Unique domain ownership and fail-closed unassigned domains.
- Explicit roles and audited `mail.domain.override` behavior.
- Sender ownership/domain/campaign enforcement and scoped aliases.
- Recipient-domain-derived inbound campaign routing.
- Suspension with history preservation and reconciliation findings.
- Canonical Keycloak issuer/roles/scopes artifact.
- Kong HTTPS/OIDC/rate/size/correlation route artifact.
- Six inactive n8n orchestration workflow declarations.
- Stalwart isolated Compose definition and loopback deployment.
- OpenAPI contract and 14-domain registry/DNS plan.

## Evidence

```text
MAIL_POLICY_TESTS=9_PASS_0_FAIL
DOMAIN_REGISTRY_VALID=PASS
MAIL_DOMAINS_REGISTERED=14
DOMAINS_SYSTEM_ONLY=4
DOMAINS_BLOCKED_MISSING_CAMPAIGN_ASSIGNMENT=10
GITLEAKS_NEW_MAIL_PLATFORM=PASS
STALWART_IMAGE=stalwartlabs/stalwart:v0.16
STALWART_RUNTIME_VERSION=0.16.18
STALWART_ISOLATED_CONTAINER=HEALTHY
STALWART_BOOTSTRAP_UI=HTTP_302
EXTERNAL_EMAIL_SENT=0
PRODUCTION_DNS_CHANGES=0
```

## Blocking gates

1. Ten human/corporate domains have no approved business-unit/campaign
   authority. They remain inactive by design.
2. `codestra.co` publishes two DMARC policies and must be reconciled by its DNS
   owner before mail activation.
3. The isolated Stalwart instance is in bootstrap mode. Keycloak OIDC directory,
   pre-created TEST_SYN principals, and application-password fallback policy
   require an approved admin identity and secret-backed provisioning execution.
4. Production TLS hostname/certificate, mail-server A/AAAA, PTR, firewall, and
   registrar changes are not approved as exact records.
5. Odoo workspace/views, live Kong deployment, n8n workflow imports, webmail,
   shared inbox canaries, Klyrow event bridge, backup/restore, and failure tests
   are not yet deployed/certified.
6. Independent review has not occurred; `REVIEW=APPROVED` cannot be self-issued.

## Rollback

The isolated service can be stopped with its Compose project while retaining
the two named volumes. No existing production service is on the isolated
network or uses its ports. Volume removal is deliberately excluded from the
rollback command because mailbox/config history is retained by default.
