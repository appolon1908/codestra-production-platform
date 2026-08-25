# WebSocket HA failover and failback

This procedure is fail-closed. Do not switch traffic until the change owner has
approved a maintenance window and the independent WebSocket databases have an
approved, healthy state-synchronization design. Never place credentials in this
document, command history, or evidence.

The selected design is PostgreSQL 16 physical streaming replication: one
read/write primary and one read-only hot standby, with manual fenced promotion.
The gateway image must first support passive-standby startup because the current
image performs a global session-ownership UPDATE during startup. Do not point a
second running gateway at the writable primary and do not point the current image
at a read-only replica.

```text
CHANGE_ID=<approved change record>
OWNER=<on-call platform owner>
START_STATE=primary healthy; standby healthy; public WebSocket routes to primary
PRIMARY_TARGET=127.0.0.1:18102
STANDBY_TARGET=127.0.0.1:31882
RTO_TARGET=<approved target>
```

## Mandatory gates

Record PASS for primary and standby `/healthz` and `/readyz`, PostgreSQL health,
schema/migration parity, database state synchronization, valid synthetic WSS
authentication, Prometheus gateway scrapes and readiness probes, restart counts,
rollback ownership, and the approved maintenance window. Stop if any gate fails.

## Precheck commands

```bash
docker inspect codestra-websocket-gateway-gateway-1 codestra-websocket-gateway-postgres-1 codestra-websocket-standby-031447a-gateway-1 codestra-websocket-standby-031447a-postgres-1
curl --fail --silent --show-error http://127.0.0.1:18102/readyz
curl --fail --silent --show-error http://127.0.0.1:31882/readyz
docker exec codestra-monitoring-prometheus-1 promtool check config /etc/prometheus/prometheus.yml
caddy validate --config /etc/caddy/Caddyfile
```

Use the protected `codestra-realtime-certifier` mechanism for WSS validation.
Never echo its secret or the issued access token/ticket.

## Traffic switch

The production authority is `/etc/caddy/sites/current-production.caddy`. Create
a root-owned candidate that changes only WebSocket realtime upstream occurrences
from `127.0.0.1:18102` to `127.0.0.1:31882`. Review the diff and verify every
other route is byte-identical. Back up the active file, install the candidate
atomically, validate the complete Caddy configuration, and reload:

```bash
install -m 0640 -o root -g caddy <approved-candidate> /etc/caddy/sites/current-production.caddy
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

The atomic Caddy reload changes the owner for new connections. Existing primary
connections must be drained within the approved bound before authoritative event
delivery is enabled on both gateways. Independent writable databases are not an
acceptable active/standby ownership model.

## Post-switch health and monitoring

Confirm public `/healthz` and `/readyz`, valid WSS authentication/session ACK,
standby connection metrics, primary new-connection counter stability, restart
counts, authentication failures, reconnects, delivery failures, backpressure,
latency, and database readiness. Record switch timestamps and measured RTO.

Success requires the public session to reach standby, no new primary sessions,
no duplicate/lost synthetic event, zero unexpected restarts, and all Prometheus
targets up.

## Rollback triggers

Rollback immediately on failed config validation/reload, non-200 readiness,
failed valid WSS auth, unexpected primary connections, database divergence,
event loss/duplication, restart, 5xx/auth/reconnect spike, latency breach, or
monitoring loss.

## Rollback and failback commands

Restore the exact backed-up primary-routing file atomically, then:

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

Repeat primary public health, valid WSS auth/session, routing ownership,
monitoring, log, and data-integrity checks. Failback uses the same commands and
gates after the approved observation period. Preserve both configurations,
timestamps, digests, logs, Prometheus query evidence, and the change record.

```text
TRAFFIC_SWITCH_COMMAND=atomic protected Caddy site install; validate; systemctl reload caddy
CONFIG_VALIDATION=caddy validate --config /etc/caddy/Caddyfile
RELOAD_COMMAND=systemctl reload caddy
POST_SWITCH_HEALTH=public health/readiness plus valid synthetic WSS session
WSS_VALID_AUTH_TEST=protected codestra-realtime-certifier workflow
MONITORING_CHECK=Prometheus websocket_gateway and websocket_readiness targets
ROLLBACK_TRIGGER=any health/auth/state/routing/monitoring/error threshold failure
ROLLBACK_COMMAND=restore exact primary-routing backup; validate; reload
FAILBACK_COMMAND=restore exact primary-routing backup; validate; reload; certify
SUCCESS_CRITERIA=single traffic owner, valid WSS, state integrity, monitoring up
DATABASE_PRECHECK=primary writable; standby in recovery/read-only; sender and WAL receiver streaming
REPLICATION_LAG_THRESHOLD=5 seconds, subject to approved production RPO
PROMOTION_COMMAND=approved pg_ctl promote equivalent after old-primary fencing
FENCING_COMMAND=stop old primary PostgreSQL and remove its HA endpoint before promotion
OLD_PRIMARY_DEMOTION=re-seed former primary from new authority before reconnecting it
TRAFFIC_SWITCH=atomic Caddy realtime upstream change after database promotion checks
POST_PROMOTION_DB_CHECK=one writable authority; old authority fenced; migration and state hashes match
AUTH_STATE_CHECK=replicated synthetic single-use ticket authenticates exactly once
EVENT_REPLAY_CHECK=synthetic event, ordinal, sequence and replay cursor remain identical
ROLLBACK=restore traffic only to a synchronized writable authority; never a stale former primary
FAILBACK=re-seed, stream, fence, promote, validate state, then atomically restore traffic
```
