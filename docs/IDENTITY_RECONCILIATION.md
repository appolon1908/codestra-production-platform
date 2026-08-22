# Identity reconciliation

The Codestra agent UUID links separate `agent_identity` rows for Keycloak subject, Odoo employee/user, and VICIdial user. The canonical Keycloak subject is never rewritten to match a stale downstream mapping. Duplicate external identity or conflicting active subjects are quarantined as `IDENTITY_MISMATCH` and require authoritative review; they are never auto-merged. Secrets and credentials are not mapping fields.
