# CODEX DIRECTIVE — APPLICATION SERVER A

## Server identity

```text
Role: Application Server A
Address: 65.109.65.169
Repository target: /root/codestra-production-completion
VICIdial peer: 65.21.67.207
```

## Mission

Build the primary Codestra application platform on this server and integrate it safely with the dedicated VICIdial server.

This server is responsible for:

- Odoo 19
- Odoo PostgreSQL and filestore
- Codestra middleware
- Automatic campaign design and provisioning orchestration
- n8n
- Redis
- Middleware data store when required
- Keycloak
- OAuth2 Proxy or accepted authentication gateway
- Reverse proxy and TLS
- Workers
- Reconciliation
- Monitoring and alerts
- GitHub-controlled builds and deployment

Do not return only a plan. Inspect the current repository, preserve compatible work, implement missing components, run tests, commit stable checkpoints, and produce evidence.

## Required reading

Read completely before editing:

1. `AGENTS.md`
2. `docs/AUTOMATIC_CAMPAIGN_PROVISIONING.md`
3. `docs/VICIDIAL_ADAPTER_CONTRACT.md`
4. `specs/VICIDIAL_ODOO_MAPPING_SPEC.md`

## Critical rule

Odoo, n8n, browser clients, and AI services must never write directly to VICIdial tables.

All operational VICIdial actions go through authenticated middleware on this server and the restricted adapter on `65.21.67.207`.

## First execution

1. Inventory the repository.
2. Identify existing Odoo, middleware, n8n, Keycloak, reverse-proxy, deployment, test, and monitoring code.
3. Run current tests.
4. Inventory local services, containers, databases, firewall, TLS, backups, and Git state.
5. Test read-only network reachability to `65.21.67.207`.
6. Do not open remote database access.
7. Create `reports/app-server-a/BASELINE.md`.
8. Create a gap matrix with `PASS`, `PARTIAL`, `FAIL`, `MISSING`, `BLOCKED`, and `NOT_TESTED`.
9. Begin implementation immediately after discovery.

## Automatic campaign requirement

Implement the full workflow in `docs/AUTOMATIC_CAMPAIGN_PROVISIONING.md`.

Every newly created Odoo campaign must automatically generate a complete integration design.

Behavior:

- On Odoo campaign creation: create the design request and preview automatically.
- On approval: middleware provisions disabled VICIdial resources through the adapter.
- On successful read-back: create/update inactive n8n workflow scope and write status to Odoo.
- On test approval: permit explicit activation.
- Never enable public dialing merely because a campaign was created.

Generated design includes:

- Canonical campaign ID
- Business-unit mapping
- List allocation
- User groups
- Inbound groups
- Closer groups
- Script versions
- Disposition set
- Callback and appointment policy
- Transfer policy
- IVR design when requested
- n8n workflow scope
- Reporting mapping
- Feature flags
- Test plan
- Rollback reference

## Odoo implementation

Inventory current custom addons. Extend compatible modules.

Implement or complete:

- Business units
- Campaign model and lifecycle
- Campaign blueprint
- Campaign design revision
- Campaign approval
- Integration UUID
- Provisioning status
- Actual-state view
- Drift status
- Activation status
- Agent desired state
- Campaign access rules
- Structured notes
- Dispositions
- Callbacks
- Appointments
- Calendar and activities
- Supervisor overdue queues
- Daily/weekly/monthly idempotent performance rollups
- Audit history
- Production feature-flag visibility

Use transactional outbox events. Do not make remote adapter calls inside the main Odoo database transaction.

## Middleware implementation

Implement or complete:

- Authentication and authorization
- Keycloak integration
- Business-unit isolation
- Campaign mapping registry
- Campaign blueprint engine
- Manifest generator
- Atomic resource allocator
- Provisioning orchestrator
- VICIdial adapter client
- Transactional outbox
- Idempotency
- Retry and backoff
- Dead letters
- Reconciliation
- Read-back comparison
- Policy engine
- Feature flags
- Kill switches
- Metrics
- Structured logs
- Audit
- WebSocket screen pops
- Provider-neutral notifications

Required campaign flow:

```text
Odoo outbox
→ middleware design generator
→ approval
→ resource reservation
→ signed adapter command
→ VICIdial read-back
→ desired/actual comparison
→ n8n scope generation
→ Odoo status update
→ synthetic tests
→ explicit activation
```

## n8n

- Version workflow exports in Git.
- Use middleware APIs only.
- Require authentication, idempotency key, and correlation ID.
- Keep workflows inactive until dependencies pass.
- Create per-campaign workflow scope automatically.
- Create workflow instances from approved templates rather than hand-copying workflows.
- Do not embed credentials.
- Do not write directly to VICIdial.

## Required services

Implement or validate:

- Odoo web
- Odoo workers
- Odoo cron
- Odoo PostgreSQL
- Middleware API
- Middleware workers
- Campaign provisioning worker
- Reconciliation worker
- Notification worker
- Redis
- n8n
- Keycloak
- OAuth2 Proxy
- Reverse proxy
- Metrics exporter
- Log collection
- Alerting
- Backup client

Services must have:

- Health and readiness checks
- Automatic restart
- Graceful shutdown
- Startup ordering
- Log rotation
- Resource limits
- Secret redaction

## Network policy

Only permit required traffic.

- PostgreSQL is private.
- Redis is private.
- n8n editor is authenticated.
- Middleware administrative APIs are authenticated.
- Adapter traffic to `65.21.67.207` uses an approved secure channel.
- Do not change firewall rules without preserving SSH and preparing rollback.
- Do not expose internal metrics publicly without authentication or source restriction.

## GitHub

- Identify the configured GitHub repository.
- Preserve uncommitted user changes.
- Use `release/production-activation`.
- Add CI for tests, lint, type checking, migrations, secret scanning, container builds, and workflow validation.
- Commit logical checkpoints.
- Push when credentials are available.
- Deploy exact commit SHA.
- Never commit secrets.

## Tests

At minimum:

- Odoo module install and upgrade
- Access and record rules
- Campaign create event
- Design preview generation
- Concurrent list allocation
- Approval state machine
- Provisioning idempotency
- Adapter authentication
- Adapter failure and retry
- Read-back comparison
- Existing-compatible-resource adoption
- Collision blocking
- n8n inactive-by-default
- Synthetic lead
- Duplicate lead retry
- Agent sync
- Callback
- Appointment
- Same-campaign transfer policy
- Cross-campaign rejection
- Reconciliation
- Rollback
- Daily rollup idempotency

## Production safety

All action flags start false.

Do not enable production dialing from this build until:

- Backup restore passes
- CI passes
- Adapter is healthy
- Synthetic tests pass
- Read-back matches
- Reconciliation passes
- Rollback passes
- Monitoring and kill switches work
- Approved test destinations exist
- Calling hours, consent, DNC, and recording policies pass

## Required reports

```text
reports/app-server-a/BASELINE.md
reports/app-server-a/GAP_MATRIX.csv
reports/app-server-a/IMPLEMENTATION.md
reports/app-server-a/ODOO_TESTS.md
reports/app-server-a/MIDDLEWARE_TESTS.md
reports/app-server-a/CAMPAIGN_AUTOMATION_TESTS.md
reports/app-server-a/N8N_TESTS.md
reports/app-server-a/SECURITY.md
reports/app-server-a/NETWORK.md
reports/app-server-a/BACKUP_RESTORE.md
reports/app-server-a/DEPLOYMENT.md
reports/app-server-a/PRODUCTION_GATE.md
```

## Start now

Read all required files, inspect existing work, run the current tests, create the baseline, and begin implementation. Do not stop after writing another plan.
