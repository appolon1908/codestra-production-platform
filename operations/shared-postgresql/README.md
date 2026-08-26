# Shared PostgreSQL PITR authority

This package is the non-secret desired state for the PostgreSQL cluster serving
`codestra_middleware`, Odoo, n8n, email, control-plane, and explicitly inventoried
rehearsal databases. It is separate from the Kong PostgreSQL HA change.

Production remains fail-closed until `validate-change-authority.sh` returns
`SHARED_POSTGRES_CUTOVER_GO=YES`. Source preparation alone authorizes no restart,
database mutation, middleware migration, or traffic change.

The intended sequence is: fresh logical/off-host backup, restore precheck,
consumer inventory, approved restart, WAL archive proof, encrypted physical base
backup, isolated production-generated PITR, and only then middleware write freeze.
The archive authority must be independent from the PostgreSQL host. Secrets live
under the approved protected secret backend, never in this repository.

Rollback boundary: if PostgreSQL or any consumer fails after the configuration
restart, restore the captured configuration within the approved window, restart
PostgreSQL, validate every consumer, and stop before middleware migration.

Change authority: GitHub issue #107. All `PENDING` decisions must be replaced by
accountable approvals before deployment.
