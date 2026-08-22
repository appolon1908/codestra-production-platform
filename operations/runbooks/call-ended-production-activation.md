# Finalized call-ended production activation

This runbook covers only the least-data `vicidial.call.ended` publisher. It
does not authorize live dialing, VICIdial control, callbacks, customer
communications, Odoo writes, n8n production delivery, SMS, or email.

## Invariants

- Odoo remains the business source of truth.
- Middleware remains the orchestration and mapping source of truth.
- VICIdial remains the telephony source of truth.
- The publisher reads only finalized `vicidial_log` and
  `vicidial_closer_log` rows after the protected watermark.
- SMTP, SMPP, SIP/RTP, databases, Redis, and RabbitMQ remain outside Kong.
- A merge or immutable release does not activate delivery.
- The default environment is fail-closed:
  `TEL_EVENTS_ENABLED=false`, `SEND_EVENTS=false`,
  `TEL_EVENTS_MODE=disabled`, and the kill switch present.

## Required protected inputs

Record all of the following in the approved change and evidence:

1. Exact protected commit and immutable image digest.
2. Fresh, root-owned watermark with composite ordering
   `(end_epoch, stable_source_id)`.
3. Explicit campaign and VICIdial user-group allowlists.
4. A canary budget from 5 through 10 naturally finalized events.
5. Starting ledger state and zero historical backlog eligibility.
6. Independent reviewer, maintenance tuple, rollback owner, and evidence path.

Never reuse the quarantined historical backlog as canary traffic.

## Bounded canary

Use a dedicated canary environment file with:

```text
TEL_EVENTS_ENABLED=true
SEND_EVENTS=true
TEL_EVENTS_MODE=canary
TEL_EVENTS_EVENT_BUDGET=5
TEL_EVENTS_CAMPAIGN_ALLOWLIST=<approved campaign IDs>
TEL_EVENTS_USER_GROUP_ALLOWLIST=<approved user groups>
```

Remove the delivery kill switch only inside the approved window. Run one
bounded publisher invocation. The canary must stop at its durable acknowledged
budget and must not be configured as a persistent boot service.

A delivery is successful only for HTTP 200, 201, 202, or 204. HTTP 409 is a
permanent conflict requiring evidence reconciliation; it is not an
acknowledgement. Dead-lettered events are terminal and may not be resent by
changing their ledger state.

Require evidence for:

- exactly 5–10 newly finalized, allowlisted events;
- deterministic event and idempotency keys;
- no duplicate business side effects;
- monotonic cursor advancement only after acknowledgement;
- zero dead letters and zero unapproved events;
- no calls placed and no telephony-control writes;
- no SMS, email, callback, Odoo, or n8n production side effects.

Reinstall the kill switch and return both enable flags to `false` after the
bounded run.

## Soaks and promotion

Promotion to persistent delivery requires all bounded-canary evidence plus:

1. One-hour monitored soak.
2. One-business-day monitored soak.
3. Backup and isolated restore evidence.
4. Security, telephony, compliance, and business acceptance.
5. Fresh independent approval for the exact production tuple.

Only then set `TEL_EVENTS_MODE=production`, select a reviewed per-iteration
budget (1–100), keep the same explicit allowlists, set both enable flags to
`true`, remove the kill switch, and enable
`codestra-tel-events.service`.

## Rollback

At the first unexplained conflict, dead letter, scope violation, cursor drift,
unexpected side effect, or health regression:

1. Reinstall `/etc/codestra/disable-external-delivery`.
2. Set `TEL_EVENTS_ENABLED=false` and `SEND_EVENTS=false`.
3. Stop and disable `codestra-tel-events.service`.
4. Preserve the watermark, ledger, logs, and exact runtime evidence.
5. Do not rewrite terminal ledger state or replay history.
