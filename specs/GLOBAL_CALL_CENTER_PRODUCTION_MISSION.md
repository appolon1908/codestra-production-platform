# Global Call-Center Production Mission

The platform may operate a campaign only when an exact tenant/campaign policy
binds the business owner, mode (`HUMAN_ONLY`, `AI_ONLY`, or `HYBRID`), countries,
jurisdictions, consent and DNC policy, local calling window, agents, caller IDs,
trunks, concurrency, calls-per-minute and daily ceilings.

`AI_ONLY` and the AI portion of `HYBRID` require separate authorization. General
AI dialing remains disabled. Human production dialing is manual-only until a
separately signed rollout artifact says otherwise.

Every eligible lead must pass tenant binding, campaign binding, consent, DNC,
opt-out, country, jurisdiction, timezone and calling-window validation before an
atomic reservation. A durable outbox event must be committed in the same
transaction. VICIdial executes calls; middleware reconciles events; Odoo owns
the business outcome.

The global origination kill switch dominates every campaign setting. Monitoring
must automatically stop origination for authentication bypass, tenant leakage,
wrong destination/caller ID/trunk, duplicate effective delivery, queue-age
breach, reconciliation drift, sustained Odoo failure, public adapter exposure,
or loss of required observability.

No rollout occurs until two independently authorized canaries pass and a signed
bounded-rollout policy names operators, monitoring thresholds, automatic stop
rules and rollback ownership. SMS, email, callbacks, broad n8n delivery,
recording-content access and AI remain separately gated.
