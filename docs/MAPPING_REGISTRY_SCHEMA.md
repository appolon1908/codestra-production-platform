# Mapping registry schema

Migration `migrations/control_plane/001_canonical_registry.sql` creates separate campaign, campaign target, agent, identity, extension, extension assignment, membership, job/step/result, event/delivery, reconciliation/difference, dead-letter, idempotency, and audit relations. Canonical identities are UUIDs. Destination identifiers remain external attributes and never become primary identity.

Mutable entities carry a positive monotonic `version`, desired state, actual state, and sync status. Partial unique indexes enforce one active owner per extension and one active campaign/agent/role membership. Identity uniqueness quarantines collisions instead of merging subjects. Tenant row-level policies use the authenticated middleware transaction setting `app.tenant_id`.
