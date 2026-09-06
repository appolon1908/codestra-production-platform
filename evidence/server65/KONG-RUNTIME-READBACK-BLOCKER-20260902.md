# Server 65 Kong runtime read-back blocker

Captured read-only on `2026-09-02` for `65.109.65.169`. No SSH configuration,
sudo policy, service, container, route, or deployment state was changed.

## Verified boundary

- `api.breero.com` resolves to `65.109.65.169` and its TLS certificate is valid.
- `GET /health` returns HTTP 503 through the edge.
- The response carries both Caddy and Kong response metadata, proving the request
  reaches Kong through Caddy; it does not prove which Kong service or upstream is
  failing.
- `GET /readiness` and `GET /version` return HTTP 404.
- The approved `codestra-caddyctl health` action independently reproduces the
  HTTP 503 result while `caddy.service` remains active.

## Approved-access finding

The installed production operator allows read-only `status`, `preflight`,
`collect-evidence`, and `validate-control-plane` actions. None returns a
sanitized Kong service, route, target, or upstream-health read-back. Its Kong
Admin access is embedded only in production traffic-gate operations and is not
an authorized general inspection interface.

A narrowly scoped `kong-readback` action is now proposed in the same protected
PR as this evidence. It exposes only allowlisted route, service, target-health,
plugin-scope, traffic-gate, and checksum fields and explicitly excludes plugin
configuration, route header matchers, certificates, credentials, and consumer
data. It has not been installed; arbitrary Docker, root-shell, filesystem, or
Kong Admin access was not used.

## Certification impact

```text
KONG_RUNTIME_SERVICE_READBACK=FAIL
KONG_RUNTIME_UPSTREAM_HEALTH=FAIL
KONG_API_ALIGNMENT=FAIL
CADDY_EDGE_HEALTH=FAIL
PRODUCTION_CHANGED=NO
SSH_CHANGED=NO
```

## Required owner action

The infrastructure/security owner must separately approve and install the
reviewed `kong-readback` operator extension. After installation, first inspect
the global and scoped plugins to determine whether the intentional core-Web
traffic gate explains HTTP 503. Only if that gate is absent should remediation
target a service/upstream. Then read back all 29 routes and repeat edge and route
certification through protected change control.
