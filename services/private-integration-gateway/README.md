# Codestra private integration gateway

This directory is the canonical source for the bounded gateway currently used
between Codestra middleware and private provider adapters on `37.27.128.39`.
It supports authenticated, replay-protected provider events in `middleware`
mode and a tenant/sender/route-bounded Telnexa adapter in `shared` mode.

The reviewed Nginx authority is `nginx/telnexa-private-gateway.conf`. Nginx
must enforce mTLS and overwrite the certificate-verification headers. Metrics
also require the edge-verified marker, a bounded service identity, and its
matching bearer. Event and message commands require their matching service
bearer and replay-protected signature contract behind that mTLS edge. Routine
client-certificate renewal is authorized by the dedicated client CA, exact
subject, and CRL; the rotated serial is retained for audit but is not a static
availability-breaking identity pin.

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
Every enabled customer policy must set `enabled` to the literal JSON boolean
`true` and define an exact `delivery_window` object with only `timezone`,
`start`, and `end`. The timezone is a protected, customer-specific RFC 3339
offset (`Z` or `+/-HH:MM`, bounded through `+/-14:00`) and both bounds are
zero-padded `HH:MM` local times. The end is exclusive; an end earlier than the
start represents an overnight window. Any seasonal offset change requires the
normal reviewed policy update. Missing, malformed, or currently closed windows
fail before SMS reservation or any Jasmin request.

The canonical `/v1/integrations/{email,sms,crawler}/commands` surface accepts
only a strict service/tenant/idempotency envelope behind an edge-derived mTLS
identity and scope. Commands are durably recorded in SQLite with operation,
event, attempt, semantic-request hash, and resource-version evidence. The
committed production contract keeps bounded command intake disabled pending a
separate activation review. No generic downstream dispatcher exists: when
separately enabled, newly accepted commands truthfully enter
`RECONCILIATION_REQUIRED` with
`downstream_dispatch_authority_unavailable`. They can be cancelled safely or
reconciled after an independently reviewed adapter authority is supplied; they
are never replayed automatically into a provider. Payload keys that could
carry credentials are rejected. The operation and capability APIs require the
same edge-derived identity, tenant, and explicit scope, and never permit one
service to read another service's tenant operations. The service-to-tenant
authorization map is an externally managed JSON object supplied through
`SERVICE_TENANT_BINDINGS_FILE`; absent, malformed, duplicated, or unlisted
bindings deny command and operation access. The production Compose contract
expects this file at
`/etc/kyqra-telnexa-integration/tenant-bindings.json` and mounts it as a
read-only runtime secret without committing tenant identifiers to Git.

Middleware forwarding is independently fail-closed. New authenticated events
with an exact governed mapping remain durably dispatch-eligible while the
dispatcher is paused. They are dispatched only when
`MIDDLEWARE_FORWARDING_ENABLED=true` and an HTTPS `MIDDLEWARE_EVENTS_URL`,
`MIDDLEWARE_EVENTS_CA_FILE`,
`MIDDLEWARE_EVENTS_CLIENT_CERT_FILE`, and
`MIDDLEWARE_EVENTS_CLIENT_KEY_FILE` plus the dedicated per-source API-key and
HMAC authorities are present. The client constructs one hostname-verifying
TLS 1.2-or-newer context at startup, refuses every HTTP redirect before
presenting credentials or the client identity, and refuses to start forwarding
when the CA, certificate, or private key is unavailable. Middleware mode can forward
every governed provider source. Shared mode can forward only the Telnexa
DLR/failure events it produces; it neither exposes the general provider-ingress
routes nor consumes credentials for other provider identities. Existing
database rows migrate with `dispatch_eligible=0`; the dispatcher never replays
that historical quarantine. Pausing forwarding does not quarantine new mapped
provider receipts that the gateway has already acknowledged.
Ingress paths without an exact governed `EVENT_TYPES` mapping also remain
dispatch-ineligible, even when forwarding is enabled.
Mapped callbacks must supply a non-empty bounded `tenant_id` before they are
persisted or acknowledged as dispatch-eligible.
Delivery uses the control-plane event envelope and authentication headers,
bounded response reads, exponential retries, and a five-attempt dead-letter
limit. A transport 2xx is accepted only when its bounded JSON receipt names the
exact event ID, correlation ID, duplicate flag, and known ingestion state. An
exact `replayed_event_id` response reconciles a lost receipt only after a prior
attempt reached an unknown result; it cannot authorize a first attempt. Every
attempt is durably claimed as outcome-unknown before network I/O, and an
expired claim is retryable after restart without overlapping a live request. The
committed shared-mode Compose contract keeps this source-scoped status
forwarding disabled until a separate reviewed overlay installs the outbound
mTLS identity and exact downstream URL. Both carrier-delivery authorization
gates also remain disabled.

Outbound SMS idempotency is reserved before any Jasmin interaction. A short
preflight lease permits safe recovery after a crash or dependency failure only
while carrier submission is demonstrably unstarted. The row crosses to
`submitting` immediately before the carrier call; that ambiguous state is never
automatically reclaimed, preventing a retry from creating a duplicate message.
Every live `/send` request asks Jasmin for a level-one SMS-C DLR at the private
`/internal/v1/jasmin/dlr` route. Its callback URL carries a one-attempt HMAC
capability bound to the adapter message ID, durable operation token, and exact
customer/sender/destination/route/content effect digest. Only the exact bounded
Jasmin DLR form presented through that private production handler can reconcile
`submitting` or `outcome_unknown`; unrelated receipts, altered capabilities,
terminal conflicts, duplicate form fields, and public callback URLs fail closed.
Carrier HTTP 5xx responses and other ambiguity-preserving statuses remain
`outcome_unknown` with their bounded response digest and attempt capability;
they can become terminal only through the exact attempt-bound DLR and block a
replacement idempotency key in the interim.
An `ESME_ROK` level-one receipt means only that the SMS-C accepted the submit;
it uses a private projection identity for `telnexa.sms.submitted` /
`status=submitted` and never claims handset delivery. Signed provider
`/api/v1/telnexa/dlr` ingress remains reserved for actual delivery receipts.
The gateway strips callback query material from its HTTP logs. Live startup also
requires a distinct `JASMIN_RECONCILIATION_SECRET` of at least 32 bytes.

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
