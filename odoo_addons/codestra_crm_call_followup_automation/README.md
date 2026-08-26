# Codestra CRM Call Follow-up Automation — Odoo 19

This optional addon runs SLA escalation and reminder maintenance outside the agent's post-call transaction.

## Why this is separate

Automation adds scheduled scans, durable jobs, retries, dead-letter handling, activities, and calendar repair. Keeping those responsibilities out of the core addon ensures saving the post-call form remains fast and transactional.

## Features

- one company-scoped automation policy;
- pending post-call SLA activity;
- missed callback or appointment activity;
- automatic restoration of the required 30-minute in-app and 15-minute email alarms;
- unique idempotency keys for every logical job;
- PostgreSQL `FOR UPDATE SKIP LOCKED` worker claims;
- bounded exponential retry;
- dead-letter visibility without losing the CRM record;
- manager health API and manual safe-run CTA;
- company-scoped policy and job views.

## API model

`codestra.crm.call.followup.automation.api`

- `capabilities_v1()`
- `health_v1(company_ids=None)`
- `run_once_v1(company_ids=None, limit=100)`

Only call-follow-up managers may read health or trigger a run. Normal scheduled processing uses Odoo cron under the existing service authority.

## Safety

- No telephony, carrier, VICIdial, PBX, n8n, Postal, or direct database integration is introduced.
- Activities and reminder repair are Odoo-internal operations.
- Failures are retained as retry or dead-letter jobs with sanitized error evidence.
- The popup transaction never waits for these jobs.

## Runtime acceptance

- concurrent workers process one job once;
- repeated enqueue scans create one logical job;
- retry backoff is bounded and dead-letters after the policy limit;
- pending SLA and missed callback activities are created once;
- reminder repair restores both required alarms without deleting other alarms;
- manager and company isolation pass;
- cron restart does not lose pending jobs;
- staging proves that no real customer email is sent during synthetic testing.
