# Webphone issuer transport and readiness

The Keycloak webphone issuer calls `PROVISIONING_SERVICE_URL` for
`/session`, `/renew`, `/config` and `/revoke`.
`WEBPHONE_ENDPOINT_ADAPTER_URL` belongs to the legacy endpoint-6101
provisioning routes. When `WEBPHONE_KEYCLOAK_ENABLED=true`, those legacy
routes return HTTP 410. An empty legacy URL is therefore not a missing
backend for the active session route. Do not populate it with the retired
port 8444 or with the unrelated restricted VICIdial API.

## Transport repair on Server A

The existing production provisioning certificate covers only
`provisioning-service-production`. The ambiguous `provisioning-service`
alias and the staging CA bundle do not validate that certificate.
Use `deploy/webphone/compose.production-transport.yaml` after the issuer's
existing Compose files. It preserves the issuer image, machine credentials,
feature flags, existing networks and volumes, and adds only:

- the certificate-matching HTTPS URL;
- a read-only issuer-specific trust bundle;
- membership of the existing internal provisioning network, on which the
  production service already advertises the correct DNS name.

Before applying, verify the existing network is internal and contains only
the intended provisioning service and approved consumers. Do not create a
new network or add a public listener.

Prepare the trust bundle at
`/etc/codestra/secrets/codestra-compose/provisioning/production-ca-bundle.crt`
from the issuer's current CA bundle plus the existing production public CA.
Authenticate the CA against the deployed production secret authority and
verify the server certificate's chain, validity, serverAuth purpose and
`provisioning-service-production` hostname. Never obtain a new trust anchor
from an unverified network peer. Preserve the existing public roots needed
for the Keycloak token endpoint. The public bundle must be root-owned and
readable by the issuer; private keys and machine secrets are never copied
into the repository.

Capture the old Compose file list, pinned image identity, environment
fingerprints, mounts and network membership in protected rollback evidence.
Render the complete Compose model and confirm only the two transport
environment variables, new CA mount and internal network membership change.
Recreate only `middleware-webphone-session-issuer`, with `--no-deps`,
`--no-build` and `--pull never`.

Read back the actual settings and perform HTTPS GET `/health` and `/ready`
from inside the issuer with its configured CA file. Verify the public
Keycloak token endpoint still validates with that same bundle.

## Readiness dimensions

- **Adapter transport:** use
  `https://edge.internal.codestra.agency:8443/restricted-vicidial/ready`
  from Server A's private address, with the existing client certificate
  and CA. Root-level `/ready` is not the routed adapter endpoint.
- **Issuer transport:** DNS, hostname verification, trusted chain and
  HTTP readiness must pass from inside the issuer.
- **Machine identity:** the issuer client ID must match the provisioning
  service's expected authorized party, and its dedicated protected
  credential must be accepted by Keycloak. Do not weaken the server's
  audience, authorized-party or scope checks to make a staging client pass.
- **Session and call readiness:** inspect degraded capabilities separately.
  A `/ready` HTTP 200 can coexist with disabled SIP or agent-desktop
  capabilities. It does not prove a browser session, endpoint registration
  or successful call.

No credential rotation, identity migration, call origination, recording,
external dialing, provisioning activation or TLS bypass is part of this
transport overlay.

## Rollback

Recreate only the issuer using its captured original Compose file list,
without the transport overlay, with the same pinned image and the same
`--no-deps --no-build --pull never` options. Verify its original image,
settings, mounts and network membership. Keep the newly created public CA
bundle and protected rollback evidence until the repair is accepted; the
original bundle is never overwritten.
