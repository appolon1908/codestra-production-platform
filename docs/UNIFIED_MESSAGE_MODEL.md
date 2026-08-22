# Unified message model

`messages` is the tenant-scoped ledger. It records UUID, channel, customer, external reference, request/correlation/idempotency identifiers, direction/source/campaign/workflow, sender and normalized destination, classification, content metadata, provider identifiers/status/error, integer minor-unit costs, currency, retries, and lifecycle timestamps. Full bodies and HTML are deliberately removed from persisted metadata.

Normalized states cover common, SMS, and email lifecycles while raw provider status remains separate. `(tenant_id,idempotency_key)` is unique; an equivalent retry returns the original record and a changed destination/channel/customer conflicts.

`contacts` maps one tenant/customer to Odoo partner ID, normalized phones/emails, and channel identities, preventing channel-specific duplicate contacts. Odoo is updated only through its approved middleware service layer.
