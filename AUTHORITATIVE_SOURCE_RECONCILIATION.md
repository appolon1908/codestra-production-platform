# Authoritative WebSocket + 6101 source reconciliation

Timestamp: 2026-08-18T04:28:00Z  
Server: Server A (`65.109.65.169`, `10.40.0.1`)  
Release branch: `agent/websocket-6101-immutable`

The prior local-only SHA `5b38765ff606ecbba2e0a9c9ace1af5752350e0f`
is not release authority. This release candidate starts from remote commit
`303caac62b351fc62a8a61b75b32dcffadea7283` and restores the exact build
inputs needed for all three runtime artifacts.

| Component | Reconciled source | Lock | Container build |
|---|---|---|---|
| WebSocket Gateway | `websocket_gateway/` including the deployed replay JSON correction | hash-locked `requirements.lock` generated from `requirements.in` | digest-pinned Python base and Dockerfile |
| Agent Desktop | recovered tracked source from operational checkout based on `4063a08d90fbb777cd74b68f7dd749e389a115f2`, including the TEST_SYN/6101 changes used for the current static build | `package-lock.json`; Docker uses `npm ci` | digest-pinned Node and Caddy bases |
| webphone middleware | exact Git archive of published middleware commit `4e1c87948c69c616f52f9741c46e8a7ecd515554` | hash-locked runtime and test requirement files | maintained middleware Dockerfile, runtime target |

Untracked build products, `.env` files, `node_modules`, recordings, tokens,
private keys, and customer data were excluded. Runtime images must be produced
only by `.github/workflows/websocket-6101-release.yml` from the eventual exact
authoritative commit.

The gateway no longer creates its production schema in application startup.
The maintained migration head is `0001_realtime_gateway`; the compose migration
job runs before the gateway, and application startup verifies that exact head.
Up, database restart, and rollback were tested against an isolated PostgreSQL
16 container. No shared production schema was rolled back or destructively
migrated.

Local pre-publication gates:

```text
GATEWAY_LOCKFILE=PASS
DESKTOP_LOCKFILE=PASS
MIDDLEWARE_LOCKFILE=PASS
DATABASE_MIGRATION_HEAD=0001_realtime_gateway
MIGRATION_UP=PASS
MIGRATION_RESTART=PASS
MIGRATION_ROLLBACK_TEST=PASS
GITLEAKS=PASS
SOURCE_HIGH=0
SOURCE_CRITICAL=0
AGENT_DESKTOP_TYPECHECK=PASS
AGENT_DESKTOP_UNIT_TESTS=39_PASS
AGENT_DESKTOP_BUILD=PASS
```

The authoritative SHA is intentionally recorded only after commit and remote
lookup. CI, image digests, security artifacts, approval, deployment, and call
test identifiers are not asserted by this source-reconciliation record.
