# Codestra private integration gateway

This directory is the canonical source for the bounded gateway currently used
between Codestra middleware and private provider adapters on `37.27.128.39`.
It supports authenticated, replay-protected provider events in `middleware`
mode and a tenant/sender/route-bounded Telnexa adapter in `shared` mode.

Production carrier submission is deliberately disabled in the committed
Compose contract.  Enabling it requires a separate reviewed change that sets
both `LIVE_SUBMISSION_ENABLED=true` and
`PRODUCTION_DELIVERY_AUTHORIZED=true`, supplies a non-empty
`PRODUCTION_CHANGE_ID`, and passes the consent, suppression, sender, route,
destination, audit, rollback, and approved-recipient gates.  A health response
does not authorize delivery.

## Release and installation contract

1. Merge through normal protection into `release/production-activation`.
2. Let `Private integration gateway release` build and scan the exact protected
   SHA.  Its signing job has no repository checkout.
3. Independently verify the Cosign signature and SPDX/provenance attestations
   against the protected workflow identity.
4. Pin `PRIVATE_INTEGRATION_GATEWAY_IMAGE` to the verified `@sha256:` subject and
   bind `PRIVATE_INTEGRATION_GATEWAY_SOURCE_SHA` to that same protected commit.
5. Snapshot the existing Compose file, image ID, volume, environment-file
   metadata, and unrelated containers before any rollout.
6. Render the Compose graph and validate the candidate in isolation before
   replacing only `private-app-integration-gateway-1`.
7. Read back the exact image digest, OCI revision, user, capabilities,
   read-only root filesystem, loopback binding, network membership, health,
   and both disabled delivery gates.

Never build this service from `/opt/private-integration` in production.  Never
store secret values, private keys, customer payloads, database files, or
backups in this repository.

## Recovered predecessor evidence

The untracked predecessor was inventoried read-only on 2026-09-01.  Its running
`/app/gateway.py` and host `/opt/private-integration/gateway.py` were
byte-identical with SHA-256
`c311ff082e72ea1c694d5e90612f3da1211ccaaad4e273fd98c7fad799d45f21`.
The predecessor Dockerfile and Compose hashes were respectively
`9eda035d56c107d5db01215418004759dec960d60c3f9df0f0faf395419351e5`
and `a52bde4c2d84d163d08016af26e1b06f8c4980df7e0da723be7830823edbcff1`.
These hashes establish lineage only; they are not an installation authority.
