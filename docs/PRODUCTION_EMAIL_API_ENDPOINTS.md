# Production Email API and Endpoint Map

Date: 2026-09-12
Status: implementation in Middleware PR #263; production activation remains fail-closed.

## Architectural rule

Do not create a second mail transport API and do not bypass protected migration history.

Canonical flow:

`Odoo / n8n / product -> Middleware -> Klyrow -> Postal -> recipient`

Canonical read-back:

`Postal/Klyrow -> Middleware event ingress -> communications state/events -> Odoo / product`

Middleware is the production authorization/control authority. Klyrow remains the email-provider authority.

## Middleware canonical send/read endpoints

| Method | Endpoint | Status | Purpose |
| --- | --- | --- | --- |
| `POST` | `/v1/communications/messages` | Existing | Canonical product send submission. Production email is gated before a provider command is created. |
| `GET` | `/v1/communications/messages` | Existing | Tenant-scoped message list. |
| `GET` | `/v1/communications/messages/by-idempotency` | Existing | Read original logical message by idempotency key. |
| `GET` | `/v1/communications/messages/{messageId}` | Existing | Read canonical message state. |
| `GET` | `/v1/communications/messages/{messageId}/events` | Existing | Read canonical lifecycle timeline. |
| `POST` | `/v1/communications/messages/{messageId}/cancel` | Existing | Cancel non-terminal message when supported. |

Compatibility-only singular alias: `POST /v1/communication/messages`. New callers must use the plural canonical endpoint.

## Middleware production-control endpoints

Prefix: `/platform/v1/email/production`

| Method | Endpoint | Required scope | Purpose |
| --- | --- | --- | --- |
| `GET` | `/platform/v1/email/production/status` | `email.production.read` | Read effective tenant production policy. |
| `GET` | `/platform/v1/email/production/readiness` | `email.production.read` | Read all activation blockers without changing runtime/provider state. |
| `GET` | `/platform/v1/email/production/quotas` | `email.production.read` | Read current minute/hour/day usage and limits. |
| `GET` | `/platform/v1/email/production/audit` | `email.production.read` | Read immutable control-plane audit history. |
| `POST` | `/platform/v1/email/production/authorize` | `email.production.write` | Record reviewed tenant/domain/sender/recipient/quota authorization. Does not activate sending. |
| `POST` | `/platform/v1/email/production/activate` | `email.production.write` | Activate only when all fail-closed readiness checks pass. |
| `POST` | `/platform/v1/email/production/revoke` | `email.production.write` | Revoke authorization, return to SAFE, close new sending. |
| `POST` | `/platform/v1/email/production/kill-switch` | `email.production.write` | Explicitly open/close new-send permission. Opening requires active authorization. |

Production-control endpoints require a dedicated Keycloak caller identity `production-operator`, tenant binding, and the scopes above. Mutations require `X-Correlation-ID` and `Idempotency-Key`.

Ordinary Odoo/n8n/product send authority does not grant production activation authority.

## Middleware -> Klyrow transport endpoints

These existing private transport contracts remain unchanged.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | Klyrow `/v1/email/messages` | Command-bound authenticated email submission. |
| `GET` | Klyrow `/v1/email/messages/{command_id}` | Provider-side authoritative read-back for uncertain outcomes. |

Middleware command identity remains `email.message.send.v1`, target `klyrow-email`, capability `EMAIL_DELIVERY`.

## Klyrow -> Middleware event endpoint

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/internal/provider-events/klyrow` | Signed durable event ingress for delivery lifecycle, usage, and supported inbound-mail events. |

The ingress enforces source identity, signature timestamp bounds, event binding, replay detection, and changed-payload replay conflict. Relevant lifecycle states include accepted, queued, submitted, sent, delivered, deferred, bounced, complained, rejected, failed, cancelled, unknown outcome, opened, clicked, and unsubscribed.

## Production policy modes

- `SAFE`: no production email authorized.
- `TRANSACTIONAL_CANARY`: transactional only; explicit recipient allowlist and tight quotas.
- `TRANSACTIONAL_PRODUCTION`: transactional delivery within approved tenant/domain/sender/recipient/quota policy.
- `CAMPAIGN_PRODUCTION`: separate marketing mode requiring consent/suppression/unsubscribe/compliance and explicit authorization.

Transactional activation never implies campaign activation.

## Send-path enforcement

For production email the effective order is:

1. original bearer authentication;
2. tenant authorization;
3. caller command authorization;
4. active production authorization;
5. kill switch open;
6. authorization time window valid;
7. approved domain;
8. approved sender;
9. mode/category check;
10. recipient scope / canary allowlist;
11. durable minute/hour/day quota reservation;
12. existing verified-sender validation;
13. existing verified-domain validation;
14. existing suppression check;
15. existing consent check;
16. durable command creation;
17. Klyrow adapter external-delivery gate;
18. Klyrow provider policy;
19. Postal submission.

Exact idempotent replay must return the original logical message without a second provider command or quota reservation. A locally suppressed or failed pre-provider send releases its reservation.

## Activation blockers

`POST /platform/v1/email/production/activate` fails closed while any blocker exists, including production authorization missing, SAFE mode, production deployment activation ID missing, Middleware delivery gates closed, invalid authorization window, empty domain/sender inventory, missing quotas, unregistered Postal domain, DNS check not pass, DKIM rotation incomplete, post-rotation DNS recheck incomplete, `middleware_send_eligible=false`, or `production_ready=false`.

The current domain registry intentionally keeps production activation blocked until DKIM closeout and certification are recorded.

## Durable persistence without schema-history bypass

Middleware PR #263 reuses the existing certified, immutable hash-chained `middleware_event_ledger` rather than introducing an unapproved numbered SQL migration.

It records:

- `codestra.email.production.policy.changed`
- `codestra.email.production.quota.reserved`
- `codestra.email.production.quota.released`

Policy state is event-sourced from the latest tenant policy event. Control mutations use ledger idempotency identities. Policy changes retain actor, reason, correlation ID, request hash, previous policy and new policy. Quota reservations/releases are append-only ledger events; tenant advisory transaction locks serialize quota decisions. Minute/hour/day usage is derived from active reservations minus releases.

This preserves durable audit/quota evidence while leaving the protected production migration head and history digest unchanged.

## Implementation tracking

Middleware implementation PR: `appolon1908-hue/Middleware-#263`

Production mission PR: `appolon1908-hue/codestra-production-platform#359`

Neither PR by itself authorizes live email delivery. Exact-head CI, staging, DKIM closeout, Keycloak production-operator provisioning, backup/restore, rollback rehearsal, end-to-end canary, and owner authorization remain launch gates.
