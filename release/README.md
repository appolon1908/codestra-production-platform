# Platform release manifests

This directory owns the multi-service release-manifest contract. Individual
service repositories build and sign their own immutable artifacts; the central
platform manifest binds those service attestations to one reviewed runtime
composition, contract catalog, integrated Caddy/Kong desired state, staging
evidence, rollback evidence, and production approval.

`platform-release-manifest.v1.schema.json` requires exact 40-character Git
SHAs and `sha256:` image digests. Tags, mutable branches, `latest`, incomplete
templates, and environment-specific rebuilds are not release identities.

Promotion sequence:

1. Merge service changes through protected source branches.
2. Verify each service image, SBOM, vulnerability result, provenance, and
   signature.
3. Record the exact contract catalog and runtime-composition digests.
4. Deploy those exact image digests to staging with effects disabled.
5. Attach integration, backup/restore, rollback, and monitoring evidence.
6. Record an explicit production approval.
7. Deploy the identical digests to production and preserve read-back evidence.

Release records belong on short-lived `release/<change-id>` branches and merge
into `release/production-activation`. They must never contain private keys,
tokens, credentials, customer payloads, or secret values.
