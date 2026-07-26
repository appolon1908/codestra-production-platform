# Codestra identity provisioning implementation evidence

Evidence cutoff: `2026-07-26T01:03:00Z`

## Implemented source

- Odoo module worktree: `/root/odoo19-identity-provisioning`
- Branch: `feature/identity-provisioning`
- Commit: `85b09d992902002157d885944b5dc569dd3331c3`
- Module: `codestra_identity_provisioning` `19.0.1.0.0`
- Provisioning service repository: `/root/codestra-provisioning-service`
- Commit: `2417dfc6fe0e7e092076bc8bd56a549c6a45b1d0`

The Odoo module implements versioned role templates, protected credential
metadata, extension pools and assignments, identifier reservations, external
identity links, email domains, request and step state models, append-only
audit records, employee linkage, approval controls, RBAC, and the tabbed
provisioning form. Extension 6101 is excluded by both allocation logic and a
database constraint.

The private service foundation implements typed commands, deterministic
idempotency, fail-closed disabled adapters, partial-provisioning results,
dead-letter capture, protected-file service authentication, health/readiness,
metrics, and execute/retry/read APIs. It intentionally contains no enabled
runtime adapter.

## Runtime tests

A fresh PostgreSQL database and isolated Odoo 19 container installed
`codestra_identity_provisioning` successfully. A real module-update test run
completed with zero failures and zero errors. Covered behavior:

- repeated request idempotency returns the existing request;
- normalized identifier collisions are rejected by the database;
- extension allocation skips 6101;
- role privilege changes create a new version and archive the prior version;
- the credential-reference model has no secret-value field;
- audit rows cannot be edited or deleted.

The provisioning-service engine completed three tests with zero failures:
idempotent replay, unavailable-adapter partial failure/dead-letter behavior,
and plaintext-secret rejection. These are unit tests and do not advance an
external runtime integration gate.

## VICIdial and extension discovery

The exact installed VICIdial `non_agent_api.php` documents functions including
`add_user`, `update_user`, `add_phone`, `update_phone`, campaign queries, and
inbound-group functions. No authenticated mutation was attempted. Adapter
enablement remains blocked until capability-specific request/response tests
are approved and executed.

Read-only discovery returned no endpoints, registrations, Asterisk
configuration mentions, VICIdial phone rows, or Odoo phone rows in the
proposed `6100-6599` and `6900-6999` ranges. Endpoint 6101 nevertheless has an
active staging runtime reservation and remains unavailable.

## Gates

```text
IDENTITY_MODEL_GATE=PASS
ROLE_TEMPLATE_GATE=PASS
IDENTIFIER_RESERVATION_GATE=BLOCKED_CONCURRENT_RUNTIME_TEST_REQUIRED
EXTENSION_POOL_GATE=BLOCKED_CONCURRENT_ALLOCATION_AND_RELEASE_TEST_REQUIRED
KEYCLOAK_PROVISIONING_GATE=BLOCKED_RUNTIME_ADAPTER_NOT_IMPLEMENTED
ODOO_USER_PROVISIONING_GATE=BLOCKED_ACTIVATION_FLOW_NOT_IMPLEMENTED
VICIDIAL_PROVISIONING_GATE=BLOCKED_EXACT_API_MUTATION_TEST_NOT_AUTHORIZED
SIP_PROVISIONING_GATE=BLOCKED_RUNTIME_ADAPTER_NOT_IMPLEMENTED
EMAIL_PROVISIONING_GATE=BLOCKED_PROVIDER_NOT_SELECTED
AGENT_DESKTOP_AUTHORIZATION_GATE=BLOCKED_RUNTIME_ADAPTER_NOT_IMPLEMENTED
IDEMPOTENCY_GATE=BLOCKED_EXTERNAL_RUNTIME_REPLAY_TEST_REQUIRED
PARTIAL_FAILURE_GATE=BLOCKED_EXTERNAL_RUNTIME_FAILURE_TEST_REQUIRED
RECONCILIATION_GATE=BLOCKED_RUNTIME_ADAPTERS_NOT_IMPLEMENTED
SUSPENSION_GATE=BLOCKED_RUNTIME_ADAPTERS_NOT_IMPLEMENTED
TERMINATION_GATE=BLOCKED_RUNTIME_ADAPTERS_NOT_IMPLEMENTED
SECRET_STORAGE_GATE=BLOCKED_SECRET_BACKEND_NOT_SELECTED
RBAC_ISOLATION_GATE=BLOCKED_MULTI_USER_RUNTIME_MATRIX_REQUIRED
AUDIT_GATE=PASS
SYNTHETIC_END_TO_END_GATE=BLOCKED_RUNTIME_ADAPTERS_NOT_IMPLEMENTED
ROLLBACK_GATE=BLOCKED_SYNTHETIC_END_TO_END_NOT_RUN
```

No external identity, mailbox, VICIdial user, SIP endpoint, or secret was
created. No production service was modified.
