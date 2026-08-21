# Production middleware fail-closed override

The reviewed override `compose.production-fail-closed.yaml` targets only the
Compose service `middleware` and supplies all eleven canonical production
flags as the quoted string `false`. It is appended exactly once after the
seven unique existing production Compose files. The historical duplicate
`compose.live-delivery-safety.yaml` argument is intentionally omitted.

Before use, copy the exact protected-release file to a root-owned, mode-0644
path outside the historical Compose tree and validate it with
`tools/validate_fail_closed_override.py`. Render the complete configuration
with `docker compose ... config` and confirm that only the middleware service
receives the eleven values. During the approved maintenance window, recreate
only `middleware` with `docker compose ... up -d --no-deps --force-recreate
middleware`.

Capture the existing container ID, image ID, labels, networks, mounts, health,
restart count, and exact seven-file Compose invocation before mutation. A
rollback must use the captured prior image and exact prior Compose invocation;
it must not delete volumes or recreate any other service.
