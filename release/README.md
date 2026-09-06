# Platform release manifests

This directory owns the multi-service release-manifest contract. Individual
service repositories build and sign their own immutable artifacts; the central
platform manifest binds those service attestations to one reviewed runtime
composition, contract catalog, integrated Caddy/Kong desired state, staging
evidence, rollback evidence, and production approval.

`platform-release-manifest.v1.schema.json` requires exact 40-character Git
SHAs and `sha256:` image digests. Tags, mutable branches, `latest`, incomplete
templates, and environment-specific rebuilds are not release identities.

The `release_service_ids` inventory in the pinned runtime composition is the
complete release boundary. A manifest must contain exactly one digest-bound
service record for every listed deployed component—including Caddy, Kong, Odoo,
n8n, Keycloak, data/event infrastructure, observability, and provider services.
The schema rejects partial manifests and extra duplicate service records.

Promotion sequence:

1. Merge service changes through protected source branches.
2. Verify each service image, SBOM, vulnerability result, provenance, and
   signature.
3. Record the exact contract catalog and runtime-composition digests.
4. Deploy those exact image digests to staging with effects disabled.
5. Attach integration, backup/restore, rollback, and monitoring evidence.
6. Record an explicit production approval.
7. Deploy the identical digests to production and preserve read-back evidence.

An `accepted` environment gate must embed separately pinned integration,
backup, restore, monitoring, and rollback evidence. Production additionally
requires pinned approval evidence and cannot be accepted while staging remains
pending or rejected.

Release records belong on short-lived `release/<change-id>` branches and merge
into `release/production-activation`. They must never contain private keys,
tokens, credentials, customer payloads, or secret values.
