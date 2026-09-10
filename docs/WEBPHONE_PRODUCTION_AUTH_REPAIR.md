# Production webphone client repair

The transport repair in PR #334 exposes the actual identity mismatch. The
issuer is configured as `codestra-provisioning-service-staging`, while the
production provisioning verifier requires `codestra-provisioning-service`.
The two available credential bindings were rejected on 2026-09-10. Changing a
client ID alone cannot repair a rejected secret, and weakening the verifier
would violate environment separation.

[Keycloak PR #106](https://github.com/appolon1908-hue/Keycloak/pull/106) defines the missing compatibility client, the
exact `codestra_scopes` claim and a distinct protected secret binding. The
issuer needs only the `view-users` direct realm-management role and matching
client scope mapping for its existing read-only user lookup. Keycloak's
read-only composite prerequisites are accepted; user/client/realm mutation
roles and unrelated service roles are rejected by the preflight.

## Deployment prerequisites

The identity owner's existing protected Keycloak review, certification and
credential delivery process must complete first. The client overlay updater
does not assign service-account roles or rotate an existing client secret.
Verify those separate bindings before declaring identity readiness.

Deliver the client-specific production credential into
`/etc/codestra/secrets/codestra-compose/provisioning/production-client-secret`,
using the supported protected delivery channel. Use a regular, private file
readable by the issuer's runtime UID. Do not reuse the staging credential or
the inactive provisioning adapter's credential. Do not put secret bytes in
Git, command arguments, workflow artifacts or chat.

`deploy/webphone/compose.production-auth.yaml` explicitly sets the production
client ID and selects a separate read-only secret mount; it refuses to
create a missing host secret path. It is applied after the existing transport
overlay. It changes neither the verifier nor the image, network or call flags.

Before replacing the running issuer, run the disposable candidate check from
the reviewed checkout on Server A:

```sh
sudo python3 scripts/run_webphone_auth_candidate.py
```

The launcher renders the live Compose files plus the auth overlay, rejects
unrelated changes or a different image, and runs only Python in a disposable
container with the candidate credential mounted. It uses `--rm --no-deps -T
--pull never --entrypoint python`, publishes no service ports, and does not
replace or restart the running issuer. The source preflight is supplied on
stdin. This resolves the otherwise circular requirement to validate a credential
that the existing issuer cannot yet mount.

After deployment, execute `scripts/webphone_auth_preflight.py` inside the issuer
to validate its actual configuration. It accepts optional
`--client-id` and `--secret-file` references for a candidate already delivered
through the supported secret channel; it never accepts secret values as
arguments. The default reads the issuer's actual settings.

The preflight requires canonical HTTPS URLs, certificate validation, a successful
client-credentials exchange, a verified RS256 signature, exact issuer,
authorized party, audience and provisioning scopes, short token lifetime and
minimal user-read privileges. It checks a nonexistent user's read-only lookup,
then compares unauthenticated and authenticated validation responses on a
non-mutating provisioning GET. No real user records are enumerated. Tokens,
upstream response bodies and credentials are never printed.

A successful result establishes machine authentication only. Degraded
capabilities remain explicit, and call readiness is never inferred from HTTP
200 or successful token issuance.

## Apply and rollback

Capture the current Compose file list, immutable image, settings fingerprints,
mounts and feature flags in the existing protected rollback location. Render
the full candidate Compose model and verify only the client ID, credential
path and new mount differ. Only after credential validation and the existing
deployment requirements pass, recreate `middleware-webphone-session-issuer`
with `--no-deps --no-build --pull never`. Re-run the authenticated preflight
using the deployed settings.

If any binding or authentication check fails, retain the running configuration.
If post-change validation fails, recreate only the issuer with its captured
previous Compose file list and image. Retain the protected credential for the
identity owner's rotation/revocation decision. Do not enable calling to test
an unverified authentication repair.
