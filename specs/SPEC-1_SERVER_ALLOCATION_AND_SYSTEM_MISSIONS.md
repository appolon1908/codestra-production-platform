# SPEC-1 — Server Allocation and Complete System Missions

## Status and scope

This is the approved target architecture. It does not authorize provisioning
27–39 VMs, readdressing production, moving databases, activating AI, or retiring
ports. The current two-server deployment is a transitional topology and remains
fail closed until each production gate has runtime evidence.

## Network zones

| CIDR | Zone | Mission |
|---|---|---|
| `10.10.0.0/24` | DMZ/public entry | Edge, WAF, rate limiting, load balancing |
| `10.20.0.0/24` | Application/business | Odoo, middleware APIs/workers, Keycloak, n8n |
| `10.30.0.0/24` | Data/event | PostgreSQL, Redis, NATS JetStream |
| `10.40.0.0/24` | Telephony | VICIdial, Asterisk, restricted adapters |
| `10.50.0.0/24` | AI voice | AI edge and media gateways |
| `10.60.0.0/24` | Monitoring/management | Metrics, logs, traces, alerting, administration |

## System ownership

- Odoo is the business system of record for tenants, workforce, customers,
  business leads, campaign definitions, appointments, opportunities and call
  outcomes. It does not control calls or write to VICIdial.
- Middleware is the security, authorization, transaction, routing,
  idempotency, reservation, audit, outbox and reconciliation authority.
- Keycloak owns authentication, MFA, service identities and token lifecycle.
- Redis is rebuildable fast state; PostgreSQL remains authoritative.
- NATS JetStream transports durable events and does not decide business rules.
- n8n performs delayed workflow automation only through middleware.
- VICIdial/Asterisk owns live call-center execution, agent state, dialing,
  queues, SIP/media, transfers and final telephony dispositions.
- The VICIdial adapter is the only authorized restricted control interface.
- AI edge/gateway owns media and conversation execution but invokes business
  tools only through middleware.
- Observability owns cross-system metrics, logs, traces and alert delivery.

## Target allocation

The high-availability target contains two edge nodes, two Odoo application
nodes, an HA Odoo database tier, two middleware API nodes, two middleware worker
nodes, three control PostgreSQL nodes, three Redis nodes, three NATS nodes, n8n
main/workers, two Keycloak nodes, redundant VICIdial web/dialer/database/adapter
roles, redundant AI edge/gateway roles and redundant observability. The initial
professional footprint may consolidate compatible roles to approximately
27–28 VMs while retaining network and privilege boundaries.

## Mandatory call flow

Outbound: Odoo business lead → middleware compliance and tenant authorization
→ atomic reservation → restricted adapter → VICIdial/Asterisk → human or
separately authorized AI route → durable middleware event → Odoo outcome → NATS
→ optional, separately enabled n8n follow-up.

Inbound: carrier → VICIdial/Asterisk → DID/campaign identification → middleware
campaign policy → human queue or separately authorized AI capacity → human
handoff through middleware and the restricted adapter when required.

## Non-bypass rules

Odoo, n8n, browsers, LLMs and AI gateways never write to VICIdial MariaDB.
AI never accesses Odoo, PostgreSQL, Redis, NATS administration or Keycloak
administration directly. Edge nodes never access databases, SIP credentials or
NATS administration. Privileged operations traverse the immediately adjacent
authorized control layer.

## Capacity boundary

Twenty human agents and an initial target of 100 concurrent AI calls are sizing
inputs, not activation authorization. Codec, carrier, media, database and
failure-domain load tests are required before capacity approval.
