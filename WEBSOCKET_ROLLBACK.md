# WebSocket Rollback

Gateway rollback is bounded to the gateway compose project: preserve the PostgreSQL volume, stop the gateway, restore the prior immutable image reference/config, and start it behind the unchanged Caddy route. Validate `/healthz`, `/readyz`, ticket rejection, and scoped replay before reopening agent sessions.

Desktop rollback is recoverable by stopping/removing `codestra-agent-desktop-sipjs-staging`, renaming `codestra-agent-desktop-sipjs-staging-rollback-20260817` back to the authoritative name, starting it, and checking `https://phone.codestra.agency/`. The stopped rollback container was retained; no data was deleted.

The persistent realtime volume must not be deleted during rollback. Caddy config validates before restart. `ROLLBACK_READY=PASS`.

