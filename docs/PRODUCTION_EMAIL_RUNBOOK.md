# Production transactional email operations

Status: control procedures only; this document does not authorize activation.

## Authoritative controls

| Concern | Authority | Control surface |
| --- | --- | --- |
| Production authorization, tenant scope, categories and minute/hour/day quota | Middleware | `/platform/v1/email/production/*` with the dedicated `production-operator` identity |
| New-send tenant stop | Middleware | `POST /platform/v1/email/production/kill-switch` |
| Provider delivery, sender/domain suspension, suppressions and callback retry | Klyrow | Existing platform-owner delivery-control and operations APIs |
| Business record and user-visible delivery projection | Odoo | `codestra.email.outbox` read-only view; state comes from Middleware read-back and the existing authenticated email-event callback |
| Workflow sequencing | n8n | Existing inactive workflow definitions; never an authorization or lifecycle authority |
| Global deployment rollback/source | production platform | Protected release manifest and `docs/CONTROL_PLANE_ROLLBACK.md` |

All mutation calls require the exact authenticated operator, tenant binding,
correlation ID, idempotency key, expected policy version, change ID, and a
reason. Record response bodies only after redacting identities; never record
tokens, bodies, recipients, or secrets.

## Normal transactional activation

1. Confirm the exact source lock, protected CI/reviews, immutable image digests,
   staging suite, DKIM certificate, restore rehearsal, rollback rehearsal,
   dashboards/alerts, and signed authorization record are all PASS.
2. Confirm Odoo's integration remains queued locally while
   `ALLOW_LIVE_EMAIL=false`; confirm campaigns and n8n provider writes remain
   disabled.
3. Read Middleware `status`, `readiness`, and `quotas`. Do not continue if a
   blocker exists.
4. Submit the reviewed authorization through `/authorize`. Re-read it and
   compare tenant, domain, sender, recipient scope, categories, limits, window,
   owners, provider, environment, exact SHA, and change ID.
5. Activate through `/activate`, then open Odoo live delivery for the approved
   launch window only.
6. Start at P1: one tenant, one domain, one or very small approved sender set,
   explicit recipient allowlist, and low quotas. Observe one owner-approved
   logical message through receipt, callback, Middleware projection, Odoo
   read-back, and one metering unit.
7. Expand only after the monitoring owner records the current stage PASS.

## Emergency email shutdown

1. Close the Middleware tenant kill switch immediately. This stops new command
   creation but leaves read APIs, Klyrow callback ingress, metrics and audit
   available.
2. If Klyrow already has pending items, close its native tenant send gate or
   suspend the affected sender/domain. Do not disable callback workers.
3. Set `ALLOW_LIVE_EMAIL=false` in Odoo so no new POST can leave the local
   transactional outbox; GET reconciliation remains enabled.
4. Record the correlation/change ID, actor, reason, queue depth and exact
   release identity. Preserve all outbox, event, suppression and audit rows.

## Provider failure or callback backlog

Close new sends when provider failures, missing callbacks, callback failures or
queue age exceed the authorized stop threshold. Keep Klyrow's signed callback
delivery and Middleware ingress running. Repair the provider/private route,
then replay only the existing durable callback/outbox identities. Never create
a replacement message for an unknown outcome. Drain the backlog under a low
rate and verify Odoo read-back before reopening.

## Bounce or complaint spike

Close new sends for the affected tenant. Suspend the exact sender/domain in
Klyrow if attribution is narrower than the tenant. Verify suppression rows were
created and that a second attempt is rejected before Postal. Keep complaint,
bounce and unsubscribe callbacks active. Expansion stays stopped until the
monitoring and escalation owners approve a bounded recovery.

## DKIM failure

Suspend only the affected domain/sender and close its authorized scope; do not
rewrite unrelated DNS. Validate the replacement selector in DNS and in a
controlled receiver result before retiring the old key. Private keys never
enter Git, CI output or evidence. Reauthorize the domain only after its DKIM
certificate row is complete.

## Sender/domain revocation and quota adjustment

Use Klyrow's native resource suspension for immediate delivery-boundary stop,
then replace/revoke the Middleware authorization so its approved lists match.
For any quota change, close the kill switch, issue a reviewed replacement
authorization with a new policy version/change record, re-run readiness, and
activate explicitly. Never change rate limits silently.

## Credential rotation

Rotate through the existing secret authority and mounted files. Validate the
new Keycloak/Klyrow credential in staging, restart only the affected service,
and confirm read-back before retiring the old version. Never commit or print a
credential. Credential rotation does not open a production policy.

## Rollback

Stop new sends first, keep callback ingress/observability up, and capture queue
identities. Deploy the recorded previous immutable image/config, run required
backward-compatible migrations or the separately approved database restore,
then reconcile every indeterminate Odoo/Middleware/Klyrow identity by GET. Do
not replay a POST. Follow `docs/CONTROL_PLANE_ROLLBACK.md` for the protected
release operation.

## Backup restore

Create a fresh encrypted backup, record SHA-256 and encryption/integrity checks,
and restore that exact artifact into an isolated environment. Start required
services only against restored data and validate production policy, audit,
message, event, suppression, idempotency, quota and metering records. Record
recovery duration. Never point the rehearsal at production.

## Re-enable after an incident

Require a documented root cause, preserved evidence, corrected exact release,
green staging tests, verified monitoring, updated authorization and explicit
production/monitoring/rollback owner approval. Reopen at P1 limits even if the
previous rollout had reached a later stage. Campaign mode remains disabled.
