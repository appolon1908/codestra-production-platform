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
does not authorize delivery. Each enabled customer-policy `route` resolves to
its own `JASMIN_ROUTE_<ROUTE>_API_USER` and
`JASMIN_ROUTE_<ROUTE>_API_PASSWORD` authority; the gateway never falls back to
one global Jasmin account for differently authorized routes and refuses two
logical routes that resolve to the same Jasmin username.

Middleware forwarding is independently fail-closed. New authenticated ingress
events become dispatch-eligible only when `MIDDLEWARE_FORWARDING_ENABLED=true`
in `middleware` mode and an HTTPS `MIDDLEWARE_EVENTS_URL` plus the dedicated
per-source API-key and HMAC authorities are present. Existing database rows migrate with
`dispatch_eligible=0`; the dispatcher never replays that historical quarantine.
Ingress paths without an exact governed `EVENT_TYPES` mapping also remain
dispatch-ineligible, even when forwarding is enabled.
Delivery uses the control-plane event envelope and authentication headers,
bounded response reads, exponential retries, and a five-attempt dead-letter
limit. A transport 2xx is accepted only when its bounded JSON receipt names the
exact event ID, correlation ID, duplicate flag, and known ingestion state. An
exact `replayed_event_id` response reconciles a lost receipt only after a prior
attempt reached an unknown result; it cannot authorize a first attempt. The
committed shared-mode Compose contract explicitly keeps forwarding disabled.

Outbound SMS idempotency is reserved before any Jasmin interaction. A short
preflight lease permits safe recovery after a crash or dependency failure only
while carrier submission is demonstrably unstarted. The row crosses to
`submitting` immediately before the carrier call; that ambiguous state is never
automatically reclaimed, preventing a retry from creating a duplicate message.

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
