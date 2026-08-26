# Control-plane HTTP foundation

## Purpose

This change begins the behavior-preserving decomposition of `control_plane_service/server.py`. It does not move business routes yet. Instead, it establishes a compatibility application entrypoint and extracts shared HTTP and operator-authentication behavior into small testable modules.

## Runtime path

```text
python -m control_plane_service.application
  -> ApplicationHandler
  -> legacy Handler business routes
  -> extracted HTTP/auth primitives
```

`ApplicationHandler` subclasses the existing `Handler`. The GET, POST, PUT, PATCH, CRM, messaging, crawler, operations, provider-event, and reconciliation implementations remain inherited unchanged. The compatibility entrypoint overrides only:

- compact JSON response writing and bounded form CORS;
- request-body size enforcement;
- website-form OPTIONS handling;
- trusted Kong gateway and bearer-token operator resolution.

## Extracted packages

```text
control_plane_service/
  api/
    auth.py       trusted proxy, gateway digest, tenant and fallback identity
    http.py       JSON responses, bounded body reads and form preflight
  application.py  compatibility runtime entrypoint
  server.py       existing business routes pending staged extraction
```

## Safety properties

- no new route, method, scope, provider call, database mutation, feature flag, or public port;
- no weakening of trusted-proxy, gateway-secret, tenant, role, or bearer-token checks;
- no change to response JSON encoding, body-size rejection, or form CORS headers;
- Docker continues using the same non-root image, private listener, health contract, and Compose project;
- route extraction remains blocked until the method-bound API assurance PR is accepted.

## Next decomposition stages

1. Move release identity and system health/readiness queries into `observability/`.
2. Move platform-admin read routes into `api/routes/admin.py`.
3. Move provider webhook and Postal inbound routes into `api/routes/events.py`.
4. Move messaging/preferences/crawler routes into dedicated route modules.
5. Move CRM/forms routes after their canonical contracts merge.
6. Reduce `server.py` to application assembly and legacy compatibility shims.

Every stage must preserve the existing route inventory, pass the complete platform suite, and remain source-only until a separately approved deployment release.
