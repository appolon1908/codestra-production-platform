# Current runtime inventory

Captured read-only at `2026-08-14T16:11:59Z`–`16:12:10Z`.

## Server A

- Host `middleware`; public `65.109.65.169`, private `10.40.0.1/24`.
- Linux `5.15.0-187-generic`, 12 CPU, 62 GiB RAM, 436 GiB root with 83 GiB free.
- Consolidates Odoo, PostgreSQL, Redis, loopback NATS, Keycloak, n8n,
  middleware APIs/workers, reverse proxies and monitoring.
- Public listeners are SSH and the reviewed reverse proxy on 80/443. Private
  readiness is `10.40.0.1:443`. NATS is loopback `4222/8222`.
- Multiple candidate/runtime middleware artifacts remain; this source is a
  migration source, not a SPEC-1 production topology.

## Server B

- Host `vici`; public `65.21.67.207`, private `10.40.0.2/24`.
- Linux `6.4.0-150600.23.103-default`, 20 CPU, 62 GiB RAM, 466 GiB root with
  408 GiB free.
- Zero active channels and zero active calls at capture.
- Asterisk, MariaDB, Apache, restricted adapter and observer are active; no
  failed systemd units.
- MariaDB is loopback `127.0.0.1:3306`; AMI is loopback `127.0.0.1:5038`.
- Private integration endpoints: Apache mTLS `10.40.0.2:8443`, compatibility
  `10.40.0.2:9443`, observer/readiness `10.40.0.2:9444`; no `8444` listener.
- Public SIP/WebRTC/TURN services are existing migration-source dependencies
  and require carrier/agent policy reconciliation before migration.

## Preserved state

- Odoo database/filestore isolated restore passed; RTO `00:08:41`.
- Restic snapshot `98a338a0`; 83 filestore orphans preserved.
- 1,110 historical events remain quarantined and are not replayable.
- Production calls placed by this mission: zero.
