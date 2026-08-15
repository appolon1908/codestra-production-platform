# Odoo integration

Middleware calls approved Odoo HTTP/service endpoints only. It never writes PostgreSQL. Mapping belongs in a versioned adapter registry for contacts, leads, activities, messaging history, campaigns, delivery/bounce/complaint/unsubscribe state, crawler provenance, and consent.

Every write carries tenant, correlation, causation, and idempotency identifiers. Duplicate responses return the original mapping. Odoo outages retain events for retry and eventually DLQ; recovery requires read-back/reconciliation. Production writes remain disabled until endpoint credentials and synthetic records are approved.
