# 19 — End-to-End Acceptance Matrix (Step 23)

Synthesized from `04_ODOO_READINESS.md`, `05_AGENT_DESKTOP_AND_WEBRTC.md`, `06_VICIDIAL_ASTERISK.md`, `07_MIDDLEWARE.md`, `11_EMAIL.md`, `12_SMS.md`, `13_N8N.md`. No journey below is declared PASS without cited evidence, per mission requirement.

Status legend: **PASS** / **PARTIAL** (some real hops, some missing) / **FAIL** (core requirement absent or blocked) / **UNVERIFIED** (couldn't be exercised read-only).

---

## 1. Agent login

```
Odoo login → identity validated → telephony identity mapped → extension/device ready → campaign permission loaded → agent state available
```

| Stage | Status | Evidence |
|---|---|---|
| Odoo login → identity validated | UNVERIFIED | Keycloak issuer/JWKS configured (`10_IDENTITY.md`); interactive login flow not exercised in read-only Phase 1 |
| Telephony session init (WebRTC provision) | IMPLEMENTED | `middleware/app/api/v1/webphone.py` issues short-TTL scoped SIP credentials; browser never receives privileged VICIdial creds (correct per Step 5 requirement) |
| Agent → campaign/queue/extension mapping | **PLACEHOLDER** | `CAMPAIGN="TRANSFER_TEST"`, `ENDPOINT="6197"` are hardcoded constants in `webphone.py` — every agent gets the same identity regardless of who authenticated (`AGENT-03`, P1) |
| Ready/Paused state | PARTIAL | UI toggle exists (`AgentStatus`) but models only 4 of the mission's 10 required ACD states; not confirmed wired to a real backend event stream (`AGENT-04`, P2) |

**Verdict: PARTIAL.** The plumbing to provision a WebRTC session is real and reasonably secure; the identity-to-telephony-resource mapping that would make it usable by more than one agent at a time does not exist yet.

---

## 2. Outbound call (Odoo contact → click-to-call → PSTN)

```
Odoo contact → click call → middleware → VICIdial adapter → VICIdial → Asterisk → agent → customer → call state → disposition → Odoo
```

| Stage | Status | Evidence |
|---|---|---|
| Click phone button in Odoo | **MISSING** | No `action_call`/button method on `crm.lead`; exhaustive grep of the model found only data fields (`AGENT-02`) |
| Middleware call-origination endpoint | **MISSING** | Searched `control.py`, `telephony.py`, `webphone.py`, `orchestration.py` for `originate\|dial\|click_to_call\|initiate_call` — no match anywhere in the middleware's ~62 inventoried routes (`18_API_ENDPOINT_MATRIX.md`) |
| VICIdial adapter → VICIdial → Asterisk → PSTN | BLOCKED (moot — nothing to invoke it) | `LIVE_PSTN_DIALING=false` fleet-wide even if a caller existed (`07_MIDDLEWARE.md`) |
| Call state back to Odoo | N/A | No call was ever originated |
| Disposition → Odoo | **BROKEN** | Even via manual/VICIdial-native dialing, the agent desktop's disposition save is a no-op (`AGENT-01`) |

**Verdict: FAIL.** This is not "disabled" — the feature does not exist in code. This is the single clearest gap against the mission's explicit Step 5 acceptance requirement.

---

## 3. Inbound call (PSTN → Asterisk → VICIdial → agent → Odoo popup)

```
PSTN → SIP provider → Asterisk → VICIdial inbound group → assigned agent → middleware event → WebSocket → Odoo → popup → contact/history
```

| Stage | Status | Evidence |
|---|---|---|
| PSTN → Asterisk → VICIdial inbound routing | UNVERIFIED | VICIdial inbound-group/DID config unreadable by the audit account (`VIC-P1-04`) — real telephony infra confirmed running, but routing correctness not confirmed |
| VICIdial → middleware event | PARTIAL/IMPLEMENTED | `app/core/realtime.py` fan-out with `business_unit` tenant scoping confirmed real, not just schema (`05_AGENT_DESKTOP_AND_WEBRTC.md`) |
| Middleware → authenticated WebSocket → Odoo | **IMPLEMENTED** | `RealtimeClient` in the agent desktop is a genuine reconnecting WebSocket client (Disconnected/Connecting/Connected/Reconnecting states) — satisfies the mission's explicit reconnect-behavior requirement |
| Odoo popup on `call.ringing` | **IMPLEMENTED** | Real event listener renders an "Incoming call" panel with a correct deep link (`/web#id=...&model=crm.lead&view_type=form`) back to the actual Odoo lead — the strongest working piece of the whole agent experience |
| Popup content accuracy (caller/customer/history) | PARTIAL — not independently confirmed | Popup payload plumbing looks correct (`screenPop.payload.customer_name`/`.phone`) but the surrounding CRM panel it sits in front of is mocked, so full content accuracy under live traffic is unverified (`AGENT-05`, P3) |
| Duplicate-number handling / tenant isolation | PARTIAL | Tenant isolation on the event bus is real (business_unit filtering confirmed); duplicate-number handling not independently verified in this pass |
| Agent handles call (mute/hold/DTMF/transfer) | UNVERIFIED | `phone.ts` models SIP registration states; explicit hold/DTMF/transfer *UI controls* were not located in this pass |
| Disposition/notes/callback saved → Odoo CRM updated | **BROKEN** | `mockDesktopService` — confirmed no-op, `AGENT-01` |
| Recording metadata associated | **MISSING** | `codestra_vicidial_recording` Odoo module present in source, `uninstalled` in production (`ODOO-02`) |
| Live PSTN routing itself | BLOCKED | `LIVE_PSTN_DIALING=false`, `WEBRTC_PRODUCTION_ROUTES_ENABLED=false` fleet-wide |

**Verdict: PARTIAL, trending toward FAIL for the full loop.** The notification/popup half of this journey is genuinely well-built. The journey as a *whole* — through to a saved disposition and updated CRM record — fails at the same point outbound calling does: the agent desktop's write-back to Odoo doesn't work. Even the working half cannot carry real traffic today because live PSTN dialing is kill-switched.

---

## 4. SMS

```
Odoo → middleware → SMS adapter → gateway → provider → destination → DLR → middleware → Odoo
```

| Stage | Status | Evidence |
|---|---|---|
| Odoo → middleware trigger | UNVERIFIED | Which Odoo module calls the middleware SMS endpoint was not confirmed in this pass |
| Middleware → SMS adapter | PARTIAL | `codestra-sms-api-api-1` is real and well-engineered (idempotent DLR handling, dead-letter table, fail-closed checks — `SMS-P2-01`) |
| Adapter → provider (Telnexa) → destination | **BLOCKED** | `LIVE_SMS_DELIVERY=false` fleet-wide by design (`SMS-P1-01`); also depends on the explicitly out-of-scope `codestra-provider` host |
| Provider → DLR → middleware inbox → Odoo | PARTIAL | `/internal/dlr` endpoint implemented correctly, but never receives real DLRs while kill-switched; all related n8n DLR workflows (`CP-20/21/22-SMS.*`) are inactive |

**Verdict: FAIL today, for the right reason.** Best-engineered of the three comms channels, deliberately not live pending a go-live decision — not a defect to "fix" so much as a flag to flip after sign-off.

---

## 5. Email

```
Odoo → middleware → email provider → delivery → webhook → middleware → Odoo
```

| Stage | Status | Evidence |
|---|---|---|
| Odoo → middleware | **MISSING** | Odoo's `ir_mail_server` sends direct SMTP to `mail.klyrow.com` — the middleware is never in this path at all (`EMAIL-P1-01`) |
| Middleware → email adapter | N/A | Bypassed entirely |
| Adapter → provider → recipient | PARTIAL | `beyvra-email-api` → Klyrow send endpoint exists in code but is `LIVE_EMAIL_DELIVERY=false`; separately, Odoo's own direct-SMTP path is live in config but its queue-flush cron is disabled (`EMAIL-P1-02`), so even that unintended path likely doesn't flush automatically |
| Delivery/bounce → webhook → middleware inbox → Odoo | **UNVERIFIED/BLOCKED** | n8n workflows named for exactly this (`MailBounceV1`, `MailComplaintV1`, `MailDeliveryStatusV1`, `InboundMailReceivedV1`, `MailReconciliationV1`) all exist but are inactive |

**Verdict: FAIL, and architecturally — not just gated.** This is the one channel where the actual wiring contradicts the mission's mandated architecture (middleware as the integration gateway), not merely a flag waiting to be flipped.

---

## Summary table

| Journey | Verdict |
|---|---|
| Agent login | PARTIAL |
| Outbound call (click-to-call) | **FAIL** |
| Inbound call → screen pop → CRM update | PARTIAL (notification half works; write-back half is broken) |
| SMS | FAIL (deliberately gated) |
| Email | **FAIL** (architecturally wrong, not just gated) |

None of the five journeys the mission defines as acceptance criteria passes end-to-end today.
