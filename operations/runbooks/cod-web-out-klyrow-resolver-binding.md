# COD web-out Klyrow resolver binding

Tracks `appolon1908-hue/klyrow.com#31`.

## Invariant

The service client `cod-web-out-email-production` may resolve to the single
Klyrow tenant key `COD` only when all of the following agree:

- issuer: `https://auth.codestra.co/realms/codestra`;
- exact Keycloak service-account `sub` supplied through a protected operator
  session;
- client ID: `cod-web-out-email-production`;
- registry state: `active`;
- resolver permissions: exactly `klyrow.send`, `klyrow.read`, and
  `email.status`.

The migration does not accept an email address, username, tenant header, token
claim alone, wildcard, administrator scope, or a second tenant as authority.
It never writes a real subject or credential to Git and never sends email.

## Prerequisites

1. Run against protected staging first. Keep all live-delivery and campaign
   activation flags unchanged.
2. Confirm the canonical Keycloak manifest is deployed for the exact client and
   its secret is loaded from the root-owned file path already declared by the
   repository.
3. Read the service-account user's immutable Keycloak `sub` directly from the
   canonical realm. Do not derive it from a mailbox, username or client ID.
4. Store that one-line UUID in a root-owned file with mode `0600`, outside the
   checkout. Do not capture it in CI logs or evidence.
5. Connect to the resolver registry through the existing protected libpq
   mechanism (for example a root-owned `PGSERVICE` entry or private socket).
   Do not place database credentials on the command line.

## Apply in protected staging

The SQL reads the subject from a PostgreSQL session setting. Bind it from the
protected file for this one process, require errors to abort, then clear the
shell variables:

```bash
set -euo pipefail
subject_file=/run/secrets/cod-web-out-keycloak-subject
subject="$(tr -d '\r\n' < "${subject_file}")"
test "$(stat -c '%a' "${subject_file}")" = "600"
export PGOPTIONS="-c codestra.cod_web_out_subject=${subject}"
psql -X --set=ON_ERROR_STOP=1 \
  --file deploy/kong-production-standby/identity-registry/002_cod_web_out_klyrow_binding.sql
unset PGOPTIONS subject
```

The migration locks the registry for the transaction, rejects ambiguous or
cross-tenant rows, updates only on the canonical `(issuer, subject)` key, and
reads the exact row back before commit. Reapplying it updates the existing row
rather than deleting/reinserting it, so the resolver's stable row identity is
preserved.

## Registry read-back

Capture only redacted structural evidence:

```sql
SELECT issuer,
       client_id,
       tenant_key,
       status,
       allowed_scopes,
       count(*) OVER () AS matching_rows
  FROM oidc_tenant_registry
 WHERE client_id = 'cod-web-out-email-production';
```

Expected: one row, canonical issuer, client ID above, tenant key `COD`, status
`active`, and the exact three resolver permissions. Do not print the subject,
client secret, bearer token, connection string, database password or complete
resolver response signature material.

## Resolver contract verification

Use a newly minted short-lived client-credentials token and the protected
resolver endpoint. Send one deterministic authorization read for each explicit
permission; do not add a retry loop.

For `klyrow.send`, require all of these before Klyrow is called:

- HTTP 200 over the approved authenticated transport;
- a valid resolver response signature according to the deployed resolver
  contract;
- `authorized` is exactly `true`;
- `tenant_id` is exactly `COD`;
- `permission` is exactly `klyrow.send`;
- `identity_id` is non-empty and identical on a second deliberate read-back.

Repeat for `klyrow.read` and `email.status`. Prove that another tenant, an
administrator permission, a wildcard, `klyrow.middleware.command.write`, and
an unknown subject are denied. A resolver outage, unsigned response, malformed
JSON, missing identity, or mismatch is a hard failure; do not configure a
local Klyrow bypass.

## Controlled canary boundary

Registry success does not authorize delivery. Before the one-message canary:

1. verify `support@klyrow.com` is an active allowed sender for tenant `COD`;
2. verify the approved canary recipient is not suppressed;
3. verify all existing Klyrow sender/domain, quota, billing, canary-ledger,
   idempotency and live-effect gates pass;
4. record the exact source SHA, image digest, token issuer/client, resolver
   result, recipient hash and idempotency key;
5. authorize exactly one message under the existing canary gate;
6. stop on any duplicate, mismatch, unknown outcome, delivery counter movement
   beyond one, or missing callback/reconciliation evidence.

This repository change does not execute the canary.

## Disable / rollback

Do not delete the identity row. In a reviewed transaction, lock the row, set
`status = 'disabled'`, replace `allowed_scopes` with an empty `text[]`, read it
back, and revoke the service client's active sessions/secret if compromise is
suspected. Klyrow must return a fail-closed denial after rollback. Record the
same stable identity reference without recording its raw subject.
