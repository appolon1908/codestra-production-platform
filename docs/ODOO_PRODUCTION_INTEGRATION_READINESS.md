# Odoo production integration readiness

Certification date: 2026-08-16 UTC. This record contains identifiers and results, not customer payloads or credentials.

## Production boundary

The supported customer path is `website/application -> api.codestra.co -> Kong -> bounded middleware -> Odoo 19`. Odoo JSON-RPC/XML-RPC, arbitrary models and fields, administrator operations, and `/web/*` are not customer APIs. Ports 8069/8071/8072 are Docker-private; the approved staff UI remains behind its authenticated Caddy hostname. Kong returned 404 for attempted `/jsonrpc` and `/web` routes.

Odoo `19.0-20260630` runs in `codestra-odoo-1`, database `codestra_odoo`, with filestore volume `codestra_odoo_data`. Its explicit database host is `codestra-postgres-1`; the generic `postgres` alias is prohibited in production.

## Backup and addon state

A consistent pair was captured at `/opt/codestra/backups/odoo-production-readiness-20260816T080311Z`: PostgreSQL custom dump, filestore archive, inventory, consistency evidence, and `SHA256SUMS`. All checksums passed. The restore runbook and pair validator are in `operations/restore/`.

`breero_crm` was installed in the database but absent from the running add-on path because Odoo had been recreated without the existing Breero compose overlay. The release artifact was present and current. Odoo was recreated with `compose.breero-odoo-module-67c0b02.yaml`, which mounts the versioned artifact read-only at `/mnt/breero-addons/breero_crm`. The module was upgraded after the backup. Current startup has no missing `breero_crm` warning.

## Identities and Odoo enforcement

The certified CRM API identity remains non-administrator, non-CRM-manager, unable to unlink leads, and bounded to its mapped company and business unit. The Breero integration identity is non-administrator and is now bounded to company 3 and business unit 46 (`BREERO`). Server code sets `company_id`, `business_unit_id`, and `user_id`; event payloads cannot choose them.

Rollback-only ORM tests independently proved that the CRM and Breero identities cannot see the other scope, delete leads, change their company/business-unit scope, or grant themselves administrator access. Middleware still resolves Kong consumer/site identity to a server-owned scope and rejects privileged fields and arbitrary relational/context input.

## Actual website forms

The only confirmed first-party website form implementation inspected was Booked4Seasons, with `service`, `contact`, and `partner` variants. Its relay defines strict field sets, payload limits, honeypot/timing controls, correlation and idempotency keys, normalized contact fields, and separate transactional, marketing-email, and SMS-consent evidence. A phone number does not imply SMS consent, and a service request does not imply marketing consent.

Activation is intentionally blocked: no approved Booked4Seasons Odoo company/business-unit/site mapping exists. It must not be mapped to Breero merely because the form shapes are similar. The live relay therefore remains fail-closed with HTTP 503, and no Booked4Seasons synthetic Odoo record was created. Activation requires an owner-approved company, business unit, service identity, source attribution, and Kong consumer/site mapping.

## Bounded integration evidence

A single Breero staging-HMAC synthetic event was submitted without email, SMS, PSTN, or customer data:

- event `27ac72ce-1d44-42ac-bc62-94e9123ea5be`
- aggregate `1d1f8c42-ade8-495a-8e59-ef7fe563b182`
- first submission queued; exact replay deduplicated; changed payload under the same key returned conflict
- middleware worker delivered once; Odoo ledger status `processed`, attempt count 1
- exactly one `crm.lead` was created: record 135, company 3, business unit 46, service user 58

The CRM middleware retains bounded `crm.lead.created`, `crm.lead.updated`, and `crm.activity.created` publication to the authenticated internal n8n consumer. No new broad website event schema was invented. The Breero path remains a bounded Odoo adapter; Booked4Seasons event publication is pending the approved tenant mapping.

VICIdial remains at `65.21.67.207` behind its restricted mTLS adapter. Read-only health and synthetic adapter tests are permitted; this certification does not activate a campaign, dialing, or PSTN traffic.

## Failure and rollback

Middleware maps Odoo unavailability to a controlled correlated 503. Create retries are bounded and require idempotency; the same key and body returns the same object, while a changed body conflicts. Rollback is the paired database/filestore restore plus the prior immutable addon release and compose configuration. Do not restore only one member of the pair.
