# Codestra Integration Constitution

Status: authoritative, default-deny. Owner: Codestra Security Architecture.

## Authority and responsibility

Keycloak identifies human and machine principals. Kong is the public protected
API edge. Middleware is the sole integration authority: it derives tenant and
business scope from trusted identity and membership, authorizes policy, owns
inbox/outbox/idempotency/retry/DLQ/reconciliation/audit, and selects a registered
connector. Odoo owns business records. n8n sequences asynchronous automation.
Klyrow, Postal, Telnexa, Jasmin, VICIdial and Asterisk execute provider work and
report facts. Each PostgreSQL database is private to its owning application.

The machine authority is `config/integration-policy.yaml`; interface inventory
is `config/integration-registries.yaml`. If either is absent, malformed, stale,
or inconsistent, CI and production activation must fail.

## Permitted traffic

Business mutations follow source → authenticated interface → Kong when public
edge enforcement is required → Middleware → authorization and policy → target
connector → target. Provider returns follow authenticated adapter/webhook/event
→ Middleware inbox → schema and replay validation → policy, reconciliation and
audit → business system.

Odoo may submit business intent only through Kong/Middleware and receive
authenticated, allowlisted Middleware callbacks. n8n may receive approved events
and call scoped Middleware APIs. Provider systems may call only their registered
Middleware receiver. SMTP and SMPP are execution protocols behind the Klyrow and
Telnexa contracts; they are not business-authority shortcuts.

## Prohibited traffic

Odoo must not call Klyrow, Postal, Telnexa, Jasmin, provider databases, or the
VICIdial database. Providers and VICIdial must not mutate Odoo or its database.
n8n must not access Odoo, Middleware, Klyrow, Telnexa or VICIdial databases.
Browsers and public forms must never receive privileged Odoo/provider/service
credentials or assert authoritative tenant/campaign identifiers. Applications
must not use another application's database. Exceptions are denied unless the
machine policy contains a time-bounded, approved record with owner, scope,
security review and rollback plan.

## Connector and endpoint rules

Every outbound dependency must be in the connector registry with source,
target, protocol, private endpoint, named service account, scopes, timeout,
bounded retry, circuit breaker, rate limit, schema version and owners. Secrets
are referenced from protected secret storage and never stored in registries.
Unknown connectors are disabled.

Every Codestra endpoint must be registered with method, version, exposure,
authentication, scope, tenant/campaign requirements, idempotency, rate limit,
schemas, owner and status. Public protected business routes traverse Kong.
Health endpoints disclose only safe process/readiness/release identity.

## Identity and credentials

Humans use Authorization Code with PKCE; machines use Client Credentials.
Middleware validates signature, canonical issuer, audience, authorized party,
scope and expiry. Each caller uses a named least-privilege service account.
Provider secrets remain in the Middleware connector boundary. A missing identity,
tenant authority, scope, policy fact or connector configuration causes denial.

## Events, webhooks and reliability

Retryable inbound events enter a durable inbox before business effects. Important
asynchronous effects are committed through a durable outbox. Event and webhook
schemas are versioned. The canonical envelope propagates event, causation,
correlation and trace identifiers. Identical idempotency key and logical request
returns the same result; altered replay is denied.

Webhooks require a scoped token, signature or mTLS as registered, timestamp
freshness, replay protection, schema validation and an owner. Retries are bounded
with timeout, classification, exponential backoff and jitter. Repeated dependency
failures open a per-connector circuit. Exhausted work enters a durable DLQ and is
never silently discarded. Reconciliation compares Middleware with Odoo,
automation and providers and audits safe repairs.

## Policy, privacy and audit

Middleware evaluates identity, service account, tenant, organization, business
unit, team, campaign, channel, resource, entitlement, environment, scoped feature
flags, consent, DNC/suppression, quota, rate limit, reputation, abuse state and
idempotency before execution. Every decision records actor, scope, action, safe
reason, correlation ID and time. Events and logs carry only necessary data and
mask sensitive values.

## Network and database enforcement

Databases, Redis, NATS, provider management planes and Kong Admin remain private.
Service networks and host egress rules must make prohibited direct paths
unreachable. Database roles are per application and least privilege; generic
cross-application roles are forbidden. Network reachability never grants business
authority: authentication and Middleware policy remain mandatory.

## Automation governance

Production n8n workflows are versioned, inactive by default until approved, use
registered authenticated destinations, preserve correlation/idempotency, and use
the common error path. Database nodes and unknown production URLs are release-
blocking violations. Critical transactional state never exists only in n8n.

## Enforcement and operations

`tools/check_integration_architecture.py` validates registries, source,
configuration and n8n exports and fails on critical findings. Deployment reruns
the same gate against protected source. `tools/capture_runtime_architecture.py`
creates secret-free runtime facts for drift comparison. Scheduled recertification
checks source and runtime; any unknown destination, listener, route, network,
identity or workflow endpoint alerts operations and blocks the next release.

Operations displays each registered path's health, latency, circuit, queue, DLQ
and last success. Normal remediation uses registered retry, replay and
reconciliation operations rather than SSH or direct database mutation.

## Exception process

An exception requires reason, accountable owner, systems, narrow scope, expiry,
security review, rollback plan and approval. Expired or incomplete exceptions are
invalid. Permanent undocumented exceptions are prohibited. No exception may
disable required authentication, tenant isolation, audit or secret boundaries.

## Certification rule

A PASS requires zero critical scanner findings, zero unregistered public
endpoints/webhooks, denied cross-application database paths, passing negative
auth/replay tests, deployed drift monitoring, and immutable evidence. A warning
is insufficient for a critical boundary. When evidence is absent, status is not
certified.
