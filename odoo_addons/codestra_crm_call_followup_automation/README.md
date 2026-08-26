# Codestra CRM Call Follow-up Automation

Heavy, optional Odoo 19 addon for durable post-call automation.

The agent transaction only appends immutable outbox events. A separate Odoo cron
worker delivers those events to the approved Codestra middleware with bounded
timeouts, HMAC authentication, idempotency keys, retry/backoff, dead letters,
and `FOR UPDATE SKIP LOCKED` concurrency control.

Remote delivery is disabled by default.

## Required runtime parameters

- `codestra.call_followup_automation.enabled`
- `codestra.call_followup_automation.target_url`
- `codestra.call_followup_automation.tenant_id`
- `codestra.call_followup_automation.api_key_file`
- `codestra.call_followup_automation.webhook_secret_file`
- `codestra.call_followup_automation.timeout_seconds`
- `codestra.call_followup_automation.allow_insecure_loopback` (tests only)

Secrets must be mounted as files such as Docker secrets. Do not store them in
Git or ordinary environment files.

The target is middleware only. This addon never writes directly to VICIdial,
n8n, a PBX, or a carrier.
