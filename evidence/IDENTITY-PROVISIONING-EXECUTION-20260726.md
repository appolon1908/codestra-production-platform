# Identity provisioning execution evidence — 2026-07-26

## Attributable source

- Odoo worktree: `/root/odoo19-identity-provisioning`
- Odoo commit: `4f573927ec2cc22b6c621d899e29802d9a7e707c`
- Provisioning service: `/root/codestra-provisioning-service`
- Service commit: `eea28e4815bcff3c08eb45942fc1bc68cf4308e4`
- Local test image ID (not a promotable registry digest):
  `sha256:b505f8c9ad6d7b40853c546bf717b65edd00555a1f3910e5f309fdf9261ecb11`

## Implemented controls

- Durable WAL-backed request, step, retry-attempt, and callback state.
- Aggregate and per-step idempotency with concurrent duplicate suppression.
- Targeted bounded retries; successful steps are not repeated.
- Fail-closed HTTP adapter base and explicit Keycloak, VICIdial, SIP, email,
  and Agent Desktop adapter types.
- Credentials load only from protected regular-file references; symlinks,
  empty files, and broad permissions are rejected.
- Recursive rejection of secret-bearing payload keys.
- Signed Odoo callbacks using HMAC-SHA256, timestamp replay window, strict
  schema/correlation validation, idempotent receipt, and append-only audit.
- Lifecycle routes for suspension, reactivation, termination, rotation,
  request verify/cancel, and identity reconciliation.
- Non-root distroless service image with pinned build and runtime bases.

## Clean tests

Provisioning service, Python 3.13 pinned dependency environment:

```text
7 passed in 0.40s
```

Coverage exercised restart persistence, retry targeting, concurrent duplicate
execution, recursive secret rejection, protected-file permissions, callback
signing, and callback delivery persistence.

Odoo 19 fresh database `identity_validation`, image
`odoo:19.0` resolving to build `19.0-20260723`:

```text
15 test methods; 17 test statistics
0 failed, 0 errors
```

Odoo 19 module upgrade on the installed database:

```text
16 test methods; 18 test statistics
0 failed, 0 errors
```

The upgrade suite includes idempotent service-callback application.

## Read-only runtime observations

- Keycloak health: `UP`; realm discovery returned the `codestra` issuer and
  token endpoint.
- Staging middleware `/health`: HTTP 200; response body SHA-256
  `88ef99b4027d7c5ef0b4ed31280aaecf7d921592bc7b0b28c933505deda2c55b`.
- Agent Desktop staging root: HTTP 200; body SHA-256
  `fb30489a2651487540bb49c5af0a66bc72782106255148c396c13318a3d80eca`.
- Keycloak realm source contains service clients, but no approved dedicated
  provisioning-service client credential was available to this service.
- Staging middleware explicitly reported:
  `LIVE_WRITES_ENABLED=false`, `EXTERNAL_DELIVERY_ENABLED=false`,
  `VICIDIAL_READ_ENABLED=false`, `VICIDIAL_WRITE_ENABLED=false`,
  `VICIDIAL_CONTROL_ENABLED=false`, and
  `WEBPHONE_STAGING_PROVISIONING_ENABLED=false`.
- No configured mailbox-provider provisioning credential/reference was found.
- No independently running SIP provisioning API container was present.

These fail-closed controls were not bypassed. Consequently no synthetic
external identity was created, no real runtime provisioning gate is claimed,
and no synthetic rollback could be executed.

## Gate result

```text
IDENTITY_MODEL_GATE=PASS
ROLE_TEMPLATE_GATE=PASS
IDENTIFIER_RESERVATION_GATE=PASS
EXTENSION_POOL_GATE=PASS
KEYCLOAK_PROVISIONING_GATE=BLOCKED
ODOO_USER_PROVISIONING_GATE=BLOCKED
VICIDIAL_PROVISIONING_GATE=BLOCKED
SIP_PROVISIONING_GATE=BLOCKED
EMAIL_PROVISIONING_GATE=BLOCKED
AGENT_DESKTOP_AUTHORIZATION_GATE=BLOCKED
IDEMPOTENCY_GATE=PASS
PARTIAL_FAILURE_GATE=PASS
RECONCILIATION_GATE=BLOCKED
SUSPENSION_GATE=BLOCKED
TERMINATION_GATE=BLOCKED
SECRET_STORAGE_GATE=BLOCKED
RBAC_ISOLATION_GATE=PASS
AUDIT_GATE=PASS
SYNTHETIC_END_TO_END_GATE=BLOCKED
ROLLBACK_GATE=BLOCKED
```

`BLOCKED` means the implementation/offline checks exist but the required live
staging integration was unavailable or administratively disabled. It does not
mean `PASS`.
