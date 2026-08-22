# Bounded customer CRM API

`/v1/crm` is a Kong-authenticated, versioned facade. Kong never routes customer traffic directly to Odoo. The middleware verifies a private Kong-to-middleware header and resolves the immutable pair of Kong consumer ID and custom ID to one enabled customer. That server-side record selects the Odoo company and business unit; request bodies cannot select either.

## Contract

- `POST /v1/crm/leads` requires `Idempotency-Key` and accepts only `name`, `contact_name`, `email`, `phone`, `company_name`, `source`, `campaign`, `description`, and `customer_reference`.
- `GET /v1/crm/leads/{external_id}` returns only the bounded public lead representation.
- `PATCH /v1/crm/leads/{external_id}` accepts the mutable subset of the create allowlist.
- `POST /v1/crm/activities` requires `Idempotency-Key` and accepts only `lead_external_id`, `activity_type`, `summary`, `note`, and `due_date`.
- `GET /v1/crm/account` returns the caller's mapped account and permissions without Odoo IDs.

Unknown fields are rejected. Raw Odoo IDs, company IDs, user assignment, access-control fields, arbitrary models, administrator methods, JSON-RPC, XML-RPC, and `/web/*` are not part of this route.

## Authorization and Odoo identity

The chain is `Kong consumer -> crm_customers -> company/business unit -> crm_objects -> Odoo record`. Object lookups always include the resolved customer ID before Odoo is called. Odoo then independently applies global multi-company and business-unit record rules. The dedicated `Codestra CRM API Service` user has the CRM API group and one business unit; it is not an administrator or CRM manager.

Odoo calls use the bridge's timestamped HMAC contract and a five-second timeout. Create calls are retried only behind tenant-scoped middleware and Odoo idempotency evidence. Responses map unavailable Odoo to a controlled 503 with a correlation ID.

## Persistence, audit, and events

SQLite migrations create `crm_customers`, `crm_objects`, `crm_idempotency`, and `crm_audit`. Mappings use customer-scoped external IDs and opaque middleware IDs; raw Odoo IDs are not returned. Audit stores identity, action, external ID, allowed field names, result, status, correlation, and timestamp—not submitted values.

Successful mutations publish `crm.lead.created`, `crm.lead.updated`, and `crm.activity.created` to authenticated n8n workflows CP-34 through CP-36. Delivery uses bounded retry and the existing middleware DLQ.

## Rollback

Recreate the Kong route-scoped request-termination 503 plugin, then remove the route-scoped request-transformer. Restore the previous Kong service target (`unconfigured.invalid`) only after the fail-closed plugin is present. The Odoo addon backup is under `/opt/codestra/backups/crm-api-addon-*`; the database mapping and audit tables may remain inert. Never point Kong to Odoo.

## Synthetic certification (2026-08-16)

Anonymous and invalid key were 401; disabled customer was 403; unsupported `company_id` was 422; cross-tenant read/update were 404; synthetic create/read/update/activity passed; identical create returned `duplicate=true`; Odoo contained one lead per external ID; n8n executions 122, 123, and 124 succeeded for the first create/update/activity event set. All records use the isolated `CRMTEST` business unit.
