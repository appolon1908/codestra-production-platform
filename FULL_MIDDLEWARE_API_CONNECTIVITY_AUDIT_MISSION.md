# Full Middleware API Connectivity Audit — Autonomous Codex Mission

## Mission

Perform a complete, production-safe connectivity and integration audit of every API, webhook, queue, event path, SSH/service identity, and application dependency attached to the middleware control plane.

The goal is not just to list endpoints. Inventory every real integration, test every supported direction, repair safe gaps, validate authentication and failure handling, and produce one final evidence-based PASS/FAIL matrix.

Run this mission from the middleware server and continue autonomously until every locally testable integration has a conclusive result.

## Environment

Middleware server:
- public IP: `65.109.65.169`
- private vSwitch IP: `10.40.0.1`
- repository: `appolon1908-hue/codestra-production-platform`

Shared application server:
- public IP: `37.27.128.39`
- private vSwitch IP: `10.40.0.2`

Known connected systems:
- Odoo
- n8n
- Telnexa / Jasmin SMS
- Klyrow / Mautic / Postal email
- Kyqra / Crawlee / Playwright crawler

There may be additional internal services, ingress routes, databases, queues, webhooks, proxies, monitoring components, or adapters. Discover them rather than assuming this list is complete.

## Safety rules

Do not:
- send real bulk SMS
- send real bulk email
- bypass carrier/provider restrictions
- trigger destructive Odoo business actions
- write directly to Odoo PostgreSQL
- disable firewalls globally
- expose internal services publicly
- rotate working production credentials unless required and backed up
- overwrite unrelated production configuration
- delete queues, databases, workflows, or message history

Use safe mock/simulator/test payloads whenever practical.

Use Telnexa simulator/sandbox paths for SMS.
Use Klyrow safe/test mode for email.
Use non-destructive test records in Odoo/n8n.

Back up configuration before modifying shared production ingress, firewall, reverse proxy, or secrets references.

## Git workflow

Work from branch:

`agent/middleware-n8n-control-plane`

Commit all safe code/config/docs/test changes.
Push the branch.
Update or open a PR to:

`release/production-activation`

Do not merge automatically unless repository policy and tests explicitly permit it.

## Phase 1 — Complete inventory

Inventory all middleware-related infrastructure before changing anything.

Inspect at minimum:

### Network
- `ip -br addr`
- `ip route`
- `ip neigh`
- vSwitch interface and MTU
- listening TCP/UDP sockets
- firewall/UFW/nftables/iptables
- Docker published ports
- host reverse proxy listeners

### Processes/services
- systemd services
- Docker containers
- Docker Compose projects
- reverse proxy
- middleware API/backend
- n8n
- Odoo
- Redis
- RabbitMQ
- PostgreSQL/MySQL/MariaDB where present
- workers
- schedulers
- queue consumers
- webhook workers
- monitoring/exporters

### Repository/config
Search for:
- API base URLs
- webhook URLs
- callback URLs
- Odoo URLs
- n8n URLs
- Telnexa/Jasmin endpoints
- Klyrow/Mautic/Postal endpoints
- Kyqra endpoints
- service names
- private IP references
- public IP references
- ports
- environment variables
- HMAC secrets references
- API key names
- OAuth/client credentials references
- TLS/mTLS paths
- certificate paths
- queue names
- Redis/RabbitMQ URLs
- DB connection URLs
- OpenAPI specs
- ingress routes
- health/readiness endpoints

Do not print secret values.

Create:

`docs/API_CONNECTIVITY_INVENTORY.md`

For every discovered integration record:
- system/service
- direction
- protocol
- hostname/IP
- port
- endpoint/path
- auth method
- TLS/mTLS status
- owning config file
- owning container/service
- expected health endpoint
- current status

## Phase 2 — Endpoint inventory

Enumerate every middleware HTTP/API endpoint from:
- code routes
- OpenAPI specs
- reverse proxy configs
- framework route introspection if available
- live API docs

Classify each endpoint:
- public customer-facing
- private service-to-service
- admin/internal
- health/readiness
- webhook/event ingress
- outgoing integration adapter

For every endpoint document:
- method
- path
- purpose
- auth
- tenant scoping
- request validation
- idempotency support
- rate limiting
- correlation/request IDs
- response codes
- downstream dependency

Create:

`docs/API_ENDPOINT_MATRIX.md`

## Phase 3 — Required connectivity matrix

Test all known directions individually.

### Odoo

Test:
- Middleware -> Odoo
- Odoo -> Middleware if an inbound webhook/API path exists

Verify:
- authentication
- health/read-only query
- safe create test if supported
- safe update test if supported
- duplicate/idempotent handling
- failure response
- retry behavior
- no direct DB writes

Use a clearly marked temporary integration test record where necessary and clean it up safely afterward if appropriate.

### n8n

Test:
- Middleware -> n8n
- n8n -> Middleware

Verify:
- workflow endpoint reachability
- auth
- safe workflow trigger
- expected response
- correlation ID propagation
- failure/retry behavior
- disabled workflow behavior
- webhook auth where configured

Do not modify unrelated production workflows.

### Telnexa / SMS

Test:
- Middleware -> Telnexa API
- Telnexa -> Middleware webhook/event ingress

Use simulator only unless explicitly authorized otherwise.

Verify:
- service identity/API key
- HMAC signature
- timestamp validation
- replay rejection
- idempotency
- mock message accepted
- mock DLR accepted
- duplicate DLR handling
- mock MO/inbound SMS handling
- billing event path where implemented
- low-balance event path where implemented
- timeout/retry
- DLQ behavior
- circuit breaker behavior where implemented

### Klyrow / Email

Test:
- Middleware -> Klyrow API
- Klyrow -> Middleware webhook/event ingress

Use safe/test mode.

Verify:
- API auth
- HMAC
- timestamp validation
- replay rejection
- idempotency
- mock email accepted into safe/test path
- mock delivered event
- mock bounce
- mock complaint
- mock unsubscribe
- suppression enforcement
- retry/DLQ behavior
- circuit breaker behavior

### Kyqra / Crawler

Test:
- Middleware -> Kyqra API
- Kyqra -> Middleware event/result ingress

Use safe local/test URLs only.

Verify:
- API auth
- HMAC
- timestamp validation
- replay rejection
- idempotency
- test job accepted
- progress event
- result event
- duplicate classification
- completed event
- failed event
- retry/DLQ behavior
- correlation ID through lifecycle

## Phase 4 — Service-to-service SSH audit

Inventory existing SSH aliases and service identities used for maintenance/deployment.

Check:
- `/root/.ssh/config`
- relevant key filenames
- permissions
- target users
- target private IPs

Do not expose private key contents.

Expected logical identities may include:
- kyqra-server
- telnexa-server
- klyrow-server

Do not assume aliases exist; discover actual state.

Test only safe non-interactive commands such as:

`whoami; hostname; ip -br addr`

Record PASS/FAIL.

If an SSH alias is broken but the intended key/account is known and safe to repair, repair it narrowly.

Do not weaken SSH globally.

## Phase 5 — Private vSwitch audit

Verify private connectivity between middleware `10.40.0.1` and shared server `10.40.0.2`.

Check:
- VLAN ID
- interface state
- MTU
- routes
- ARP/neighbors
- ICMP
- TCP to required service ports

Do not use or recreate `10.40.0.3` unless a real separate host later requires it.

Create a table of required private ports and confirm each one is:
- reachable privately where required
- blocked publicly where it should be private

## Phase 6 — TLS / mTLS audit

Inventory all TLS/mTLS paths.

Verify:
- certificate validity
- hostname/SAN match where applicable
- chain validity
- expiration
- auto-renew mechanism
- reload hooks
- private CA/mTLS client certs where used

Specifically inspect any private middleware ingress on ports such as 443 or 8443.

Confirm which systems use:
- ordinary TLS
- mTLS
- API key only
- HMAC only
- combined mTLS + API/HMAC

Do not replace working TLS architecture unless necessary.

## Phase 7 — Authentication and authorization tests

For each service connection test both positive and negative cases.

Positive:
- valid credential succeeds

Negative:
- missing credential rejected
- invalid credential rejected
- revoked credential rejected if testable
- wrong tenant rejected
- wrong service identity rejected

Where HMAC is used:
- valid signature accepted
- invalid signature rejected
- stale timestamp rejected
- replayed event rejected

Where RBAC is used:
- unauthorized role rejected
- tenant isolation enforced

## Phase 8 — Idempotency and duplicate protection

For every write/event endpoint that should be idempotent:

Send the same request twice with the same idempotency key/event ID.

Confirm:
- no duplicate SMS billing
- no duplicate email event processing
- no duplicate Odoo records
- no duplicate crawler records
- no duplicate n8n business action where middleware is responsible for dedupe

Document endpoint-specific idempotency behavior.

## Phase 9 — Retry, queue, outbox, and DLQ audit

Discover all queue/outbox/DLQ systems.

Test safely:
- transient failure
- retry
- exponential backoff where configured
- bounded attempts
- terminal dead-letter state
- manual replay if supported
- audit log for replay

Verify events survive:
- worker restart
- container restart

Do not purge production queues.

## Phase 10 — Circuit breaker and dependency outage behavior

Where implemented, test circuit breakers using safe local mechanisms or controlled temporary mock failures.

For each downstream dependency record:
- threshold
- open state
- half-open behavior
- recovery
- alert/metric

Do not take real production services offline if a simulator/mock can test the same path.

## Phase 11 — Correlation and traceability

For one representative workflow per system, confirm a single correlation ID/request ID can be traced across logs/events.

Required flows:

SMS:
Odoo/n8n -> Middleware -> Telnexa -> simulator/Jasmin -> DLR -> Middleware -> n8n/Odoo

Email:
Odoo/n8n -> Middleware -> Klyrow -> Postal safe/test path -> event -> Middleware -> n8n/Odoo

Crawler:
Middleware -> Kyqra -> worker -> result -> Middleware -> n8n/Odoo

Record whether correlation IDs are preserved at each hop.

Repair safe gaps in logging/headers/event envelopes where practical.

## Phase 12 — Odoo integrity audit

Prove there are no direct middleware writes to Odoo PostgreSQL.

Search code/config for direct DB credentials/connections to Odoo DB.

If found:
- classify whether legitimate read-only maintenance or unsafe application coupling
- migrate application writes to approved Odoo API/service layer where safe

Test representative Odoo flows:
- contact/lead read
- safe create/update if supported
- SMS event update
- email event update
- crawler result update
- opt-out/preference update where implemented

## Phase 13 — n8n governance audit

Inventory workflows connected to middleware.

For each relevant workflow document:
- workflow name/ID
- trigger source
- middleware event
- Odoo destination/action
- active/inactive
- credential dependency
- error workflow
- retry behavior
- version/export path if Git-managed

Detect:
- orphaned webhooks
- duplicate workflows
- disabled required workflows
- public unauthenticated webhooks
- hard-coded secrets
- hard-coded obsolete IPs/ports

Fix safe issues.

Do not delete workflows merely because they appear unused without evidence.

## Phase 14 — Firewall and exposure audit

Verify middleware and shared host exposure.

Required:
- only intended public ports exposed
- private APIs restricted to private network where designed
- Redis private
- PostgreSQL private
- RabbitMQ private
- Docker socket not exposed
- Jasmin management private
- crawler debug/browser ports private
- internal Mautic/Postal admin/internal endpoints protected appropriately

Do not globally disable UFW/nftables.

If a required narrow allow rule is missing, add the narrowest persistent rule possible and document it.

## Phase 15 — Health/readiness audit

Inventory every health/readiness endpoint.

Test:
- middleware
- n8n
- Odoo
- Telnexa
- Jasmin
- Klyrow
- Postal
- Mautic
- Kyqra
- queues/databases where health endpoints/metrics exist

Distinguish:
- process alive
- ready for traffic
- dependency degraded

## Phase 16 — Observability audit

Verify Prometheus/Grafana or existing monitoring sees:

Middleware:
- request rate
- error rate
- latency
- queue depth
- DLQ
- dependency health

Telnexa:
- SMS submitted/delivered/failed
- provider state
- DLR latency

Klyrow:
- email queue/sent/bounced/complaints

Kyqra:
- jobs/results/workers

n8n:
- execution failures
- workflow latency where available

Add missing safe metrics where practical.

## Phase 17 — DNS and hostname dependency audit

Inventory all configured hostnames used by integrations.

Check for stale references to:
- old public IPs
- obsolete `10.40.0.3`
- wrong subdomains
- localhost where private address should be used

Do not change public DNS from the server unless explicitly supported and authorized.

Document any required manual DNS action.

## Phase 18 — Automated integration test suite

Create a repeatable integration audit command/script.

Suggested path:

`scripts/full-connectivity-audit.sh`

and/or application-level test harness.

It must:
- avoid printing secrets
- have timeouts
- distinguish PASS / FAIL / BLOCKED / SKIPPED-SAFE
- avoid destructive operations
- support safe mode by default

Create machine-readable output such as:

`artifacts/connectivity-audit.json`

and human-readable:

`CONNECTIVITY_AUDIT_REPORT.md`

## Required final PASS/FAIL matrix

The final report must include at minimum:

| Integration | Direction | Network | Auth | Functional | Idempotency | Retry/DLQ | Overall |
|---|---|---|---|---|---|---|---|
| Odoo | Middleware -> Odoo | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL/N/A | PASS/FAIL/N/A | PASS/FAIL/BLOCKED |
| Odoo | Odoo -> Middleware | ... |
| n8n | Middleware -> n8n | ... |
| n8n | n8n -> Middleware | ... |
| Telnexa | Middleware -> Telnexa | ... |
| Telnexa | Telnexa -> Middleware | ... |
| Klyrow | Middleware -> Klyrow | ... |
| Klyrow | Klyrow -> Middleware | ... |
| Kyqra | Middleware -> Kyqra | ... |
| Kyqra | Kyqra -> Middleware | ... |

Also include SSH/service identity status separately.

## Evidence requirements

Every PASS must have evidence such as:
- HTTP status/result
- safe response body summary
- log/correlation ID
- test name
- queue/event confirmation

Every FAIL must state:
- exact failing layer
- error
- probable cause
- attempted repair
- remaining action

Every BLOCKED must state:
- external dependency/credential/provider action required
- exact owner action needed

Do not mark anything PASS merely because configuration exists.

## Auto-repair policy

Codex may autonomously repair safe issues including:
- wrong internal base URL
- obsolete private IP reference
- missing health route
- missing safe firewall allow rule
- missing reverse proxy private route
- broken environment variable wiring
- missing retry/backoff config
- missing HMAC validation tests
- missing idempotency logic/tests
- missing correlation ID propagation
- missing health check
- missing documentation
- broken Docker service dependency wiring

Codex must not autonomously:
- rotate unknown production credentials without necessity
- send real bulk communications
- change carrier/provider production routes without approval
- alter financial balances except explicit reversible test fixtures
- delete production workflows/data
- expose private services publicly

## Final documentation

Create/update:

- `CONNECTIVITY_AUDIT_REPORT.md`
- `docs/API_CONNECTIVITY_INVENTORY.md`
- `docs/API_ENDPOINT_MATRIX.md`
- `docs/INTEGRATION_TESTING.md`
- `docs/SERVICE_IDENTITIES.md`
- `docs/NETWORK_PORT_MATRIX.md`
- `docs/N8N_ODOO_CONNECTIVITY.md`
- `docs/TELNEXA_CONNECTIVITY.md`
- `docs/KLYROW_CONNECTIVITY.md`
- `docs/KYQRA_CONNECTIVITY.md`
- `docs/TLS_MTLS.md`
- `docs/RETRY_DLQ.md`
- `DEPLOYMENT_REPORT.md`

## Definition of done

Mission is complete only when:

1. every discovered API/integration is inventoried
2. every locally testable direction has a PASS or FAIL result
3. authentication positive/negative tests are complete
4. HMAC/replay tests are complete where used
5. idempotency tests are complete
6. retry/DLQ behavior is validated where implemented
7. private network/port exposure is verified
8. Odoo API path is validated and no direct app DB writes remain
9. n8n workflow connectivity is mapped and tested
10. Telnexa simulator path is tested end to end
11. Klyrow safe/test path is tested end to end
12. Kyqra safe crawler path is tested end to end
13. correlation IDs are traced across representative flows
14. TLS/mTLS status is documented and tested
15. monitoring/health coverage is verified
16. safe gaps have been repaired and retested
17. final PASS/FAIL/BLOCKED matrix exists with evidence
18. reusable audit scripts/tests exist
19. branch is committed/pushed
20. PR is updated/opened to `release/production-activation`

Proceed autonomously from inventory through repair, retest, documentation, Git commit/push, and final report.

Only stop when blocked by:
- missing external credentials
- carrier/provider approval
- DNS/provider control outside the server
- destructive changes affecting unrelated production data
- an existing production integration whose intended behavior cannot be safely inferred

When blocked on one integration, continue auditing and repairing every other integration that remains locally executable.