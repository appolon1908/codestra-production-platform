# 12 — SMS System Audit

Phase 1, read-only. Evidence from `codestra-app` host: container inspection, `/opt/codestra/sms-api` source review (`app/main.py`, `app/event_worker.py`, migrations, README), Odoo `ir_config_parameter` read-only query. No SMS sent.

## System Map

- **Carrier adapter:** SMS README states plainly: *"The only carrier adapter is the approved restricted Telnexa endpoint."* No Jasmin/SMPP integration found (`grep -ri smpp|jasmin` only matches doc/README text, no actual SMPP client code) — this is an **HTTP-API integration to Telnexa**, not an SMPP gateway, contrary to the mission spec's "Jasmin or equivalent / SMPP" assumption.
- **Public contract** (behind Kong, `/v1/sms` stripped): `POST /messages`, `GET /messages/{id}`, `GET /messages/{id}/status`. Private `POST /internal/dlr` requires a separate bearer token, not publicly routed without Kong auth — correct privilege separation.
- **Cross-host coupling:** `codestra-provider` (10.40.0.4) hosts "Telnexa" — the same host excluded from this audit as a separate product. SMS delivery is therefore dependent on infrastructure outside this audit's scope, same pattern as email (see `11_EMAIL.md`).

### Finding SMS-P1-01 — Live SMS submission is deliberately disabled platform-wide (fail-closed)
**Severity:** P1 (production blocker — by design, not a defect)
**Component:** `codestra-sms-api-api-1`, `codestra-sms-api-event-worker-1`
**Observed evidence:** Both containers run through `/opt/codestra/safety/live-delivery-admission.sh`, a wrapper entrypoint that refuses to start (`exit 78`) unless `LIVE_SMS_DELIVERY`, `LIVE_EMAIL_DELIVERY`, and `LIVE_PSTN_DIALING` are **all** exactly `"false"`. `compose.live-delivery-safety.yaml` sets `LIVE_SMS_DELIVERY: "false"` for both services. README confirms: *"`LIVE_SUBMISSION_ENABLED=false` is intentionally fixed for initial certification, so synthetic acceptance persists all state without contacting Jasmin or a carrier."*
**Expected state:** Live carrier submission enabled for production.
**Current state:** System is in **synthetic/certification mode** — messages are accepted, persisted, and state-transitioned, but never actually reach Telnexa or a handset.
**Risk:** None currently (this is a safety feature working as designed) — but it means the mission's STEP 23 "SMS" end-to-end journey **cannot pass** until this is deliberately flipped, and flipping it is a go-live decision, not a bug fix.
**Recommended fix:** N/A for Phase 1 — this is correctly-implemented pre-production gating. Flag for Phase 2 planning: define the go-live checklist item to flip `LIVE_SMS_DELIVERY=true` after explicit sign-off.
**Repository:** `codestra-production-platform` / dedicated `sms-api` (unclear which repo owns `/opt/codestra/sms-api` — see `03_GITHUB_RUNTIME_RECONCILIATION.md`).
**Suggested branch:** n/a (config flag flip, not code change).

### Finding SMS-P2-01 — Production foundations look solid, worth confirming under load
**Severity:** P2 (positive finding, verify claim)
**Component:** `app/main.py`
**Observed evidence:** DLR handler dedups on `provider_event_id` with `SELECT ... FOR UPDATE` before insert (idempotency + row-level locking); dead-letter table `sms_dlr_dead_letters` for malformed/unmatched DLRs; explicit fail-closed check: *"Fail closed unless provider delivery state matches the requested mode"* raises `RuntimeError` on mismatch between requested and actual carrier submission state.
**Current state:** Code-level review only — no load/concurrency test run (Phase 1 is read-only). Migrations show iterative hardening (`002_synthetic_certification.sql`, `003_sms_path_completion.sql`, `004_sms_event_fanout.sql`) suggesting this was actively remediated, not first-draft code.
**Recommended fix:** None blocking; include in Step 24 test-suite run (`tests/test_sms_completion.py` exists — run it, don't just read it, in a follow-up non-Phase-1 pass).

### Finding SMS-P3-01 — Odoo-side SMS config is minimal
**Severity:** P3
**Observed evidence:** Only two SMS-related `ir_config_parameter` keys exist: `codestra.provisioning.allow_live_sms`, `codestra.sms.production`. No visibility (from this host) into their current boolean values without a deeper query — did not expand further, low materiality given SMS-P1-01 already blocks live delivery regardless of these flags.

## Full Path Trace (Step 16 requirement)

| Hop | Status | Evidence |
|---|---|---|
| Odoo → Middleware | UNVERIFIED — not confirmed which Odoo module calls the middleware SMS endpoint; out of this fork's direct code-read budget. |
| Middleware → SMS adapter → gateway | **PARTIAL** | `codestra-sms-api-api-1` is real, production-shaped, but gated fail-closed (SMS-P1-01). |
| Gateway → Provider (Telnexa) → Destination | **BLOCKED** | Kill-switched; also depends on out-of-scope `codestra-provider` host. |
| Provider → DLR → Middleware inbox → Odoo | **PARTIAL** | `/internal/dlr` endpoint is implemented with idempotent processing (SMS-P2-01), but never receives real DLRs while kill-switched. n8n DLR-related workflows (`CP-20-SMS.RECEIVED-V1`, `CP-21-SMS.DELIVERED-V1`, `CP-22-SMS.FAILED-V1`, etc.) are all **inactive** — see `13_N8N.md`. |

## Verdict for this domain
SMS is the **best-engineered** of the email/SMS/n8n trio (clear idempotency, dead-letter handling, fail-closed safety), but is **not live** by explicit design pending a go-live decision. STEP 23's "SMS" journey: **FAIL** today, but for the right reason (deliberate safety gate, not brokenness).
