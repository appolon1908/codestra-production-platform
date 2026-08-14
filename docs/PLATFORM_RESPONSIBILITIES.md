# Platform responsibilities and production gates

## Secrets and PKI

Keys are environment- and direction-specific, stored outside Git, readable only
by the owning service, rotated with overlap, and identified by non-secret key ID
and fingerprint. Production and staging CAs, mTLS identities and HMAC keys are
separate. Renewal validates identity, SAN, EKU, chain and post-swap readiness,
then rolls back on failure.

## Artifact registry and supply chain

GitHub Releases is the initial immutable artifact registry. The protected
release workflow binds the archive, CycloneDX SBOM, provenance, deployment and
rollback manifests to the exact protected SHA, signs their checksum manifest,
verifies the signature independently and publishes an immutable SHA tag. Live
servers may deploy only a verified digest; live builds are prohibited.

## Odoo filestore

The transitional local volume is backed up as a database/filestore pair with a
shared backup ID, file manifest, ownership metadata, encryption and isolated
restore validation. Phase 2 must select replicated shared storage or object
storage compatible with Odoo attachment semantics and prove failover.

## Recordings and object storage

Telephony storage owns media. Odoo and middleware store only authorized metadata
and opaque references. Object storage requires encryption, tenant-scoped access,
retention/legal-hold policy, audit logging and time-limited retrieval; recording
content access remains disabled until separately approved.

## RPO, RTO and disaster recovery

Each data owner publishes measured RPO/RTO, encrypted off-server backups,
isolated restore evidence and rollback ownership. A backup without a successful
restore is not accepted. Cross-zone failover is Phase 2 infrastructure work.

## Discovery, time and firewall

Internal DNS uses environment-specific names and private addresses. All nodes
must use authenticated time synchronization because HMAC and replay protection
depend on bounded skew. Firewalls default deny between zones and allow only
documented source, destination, port and protocol tuples. Public integration and
database exposure is prohibited.

## Monitoring and kill switch

Metrics and alerts cover service readiness, certificate expiry, mTLS/HMAC
failure, replay, tenant rejection, queue age, dead letters, reconciliation,
backup failure, disk/capacity, SIP probes and public listener drift. The global
origination kill switch is fail closed and independent of campaign state.
