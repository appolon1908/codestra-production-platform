# 05 — Agent Desktop, WebRTC, Click-to-Call, Screen Pop, Session Management

Scope: Steps 4-8 of the mission (agent calling experience, click-to-call, inbound screen pop, agent session management, WebRTC/agent phone). Host: `codestra-app`. Read-only source review of `/opt/codestra/agent-desktop` (git repo, source of truth per its container's `org.opencontainers.image.source` label pointing to `github.com/Codestra-SRL/codestra-middleware` — note: **the agent-desktop image is built from the middleware monorepo**, not a separate repo, despite living in its own `/opt/codestra/agent-desktop` checkout on disk) and `/opt/codestra/middleware/app/api/v1/{webphone,telephony}.py`, `app/core/realtime.py`.

## Running agent-phone containers (ground truth for "what agents actually use" — Step 8)
```
codestra-agent-desktop-sipjs-staging   ghcr.io/codestra-srl/codestra-agent-desktop@sha256:c13d3...
    labels: codestra.environment=STAGING, codestra.external-dialing=disabled
codestra-agent-desktop-preview         codestra/agent-desktop:preview-6101
3x codestra-agent-desktop-*-rollback-* (all Exited, kept for rollback reference)
```
**There is no running container whose name or label indicates a production agent desktop.** The only live instance is explicitly labeled `STAGING` with `external-dialing=disabled`. This is the single strongest piece of evidence in this report.

## Architecture as actually implemented (not as documented)

Agent-side calling is **WebRTC via SIP.js**, registered directly to Asterisk — not "click a phone icon inside an Odoo form and have the backend originate the call." Concretely:

- `middleware/app/api/v1/webphone.py` issues short-lived (`TTL_SECONDS = 300`), scoped SIP credentials to the browser: ephemeral password (`secrets.token_urlsafe(48)`), a specific `authorization_username` ("6101"), `permitted_call_scope: ["6000"]`, `role: "SETTER"`, and TURN credentials limited to `turns:vicidial-staging.codestra.agency:5349`. **The browser never receives privileged VICIdial admin/API credentials** — this part of Step 5's requirement is correctly implemented (good finding, credit given).
- `CAMPAIGN = "TRANSFER_TEST"` and `ENDPOINT = "6197"` are **hardcoded constants** in `webphone.py`, not derived from the authenticated agent's actual campaign/extension assignment. Every browser session that provisions gets the same test campaign and endpoint regardless of who's logged in.
- `middleware/app/api/v1/telephony.py` handles **extension pool reservation/provisioning** (`/extensions/reserve`, `/provisioning`, `/provisioning/{id}/activate|suspend|deprovision|rollback`) — this is real, has an audit endpoint, idempotency-shaped request IDs, and a `_fail_closed_action` helper (good production pattern — fails closed rather than silently succeeding on error).
- There is **no click-to-call endpoint** anywhere in the middleware (`control.py`, `telephony.py`, `orchestration.py`, `webphone.py` were all searched for `originate|dial|click_to_call|initiate_call` — no match) and **no such action method in the Odoo `crm.lead` model** (`codestra_vicidial_crm/models/crm_lead.py` has only data fields, no `action_call`/button method). The intended flow (browser → middleware → VICIdial adapter → Asterisk → PSTN) described in the mission's Step 5 diagram **does not exist as code** in this environment. Agents would have to dial manually through the SIP.js softphone or rely on VICIdial's own predictive/manual dialer — Odoo is not wired as the call trigger.

## Agent Desktop UI — real vs. mock (Step 4, Step 7)

Read directly from `/opt/codestra/agent-desktop/src/App.tsx` and `src/services/desktop.ts`:

```ts
// services/desktop.ts (verbatim, abridged)
const data: DesktopData = { lead: { id:"SYN-9001", name:"John Smith", ... }, history:[...], team:[...], ai:{...} };
export const mockDesktopService: DesktopService = {
  async load(){ await pause(); return structuredClone(data) },
  async saveNotes(){ await pause() },
  async disposition(){ await pause() },
  async scheduleCallback(){ await pause() },
};
```
`App.tsx` wires the entire CRM/lead/disposition/callback/notes/supervisor UI to this mock service:
```
data = await mockDesktopService.load()               // hardcoded fake lead "John Smith" / "SYN-9001"
<LeadDetailsModule onSave={notes => mockDesktopService.saveNotes(...)}/>     // no-op, just sleeps
<DispositionModule onSave={value => mockDesktopService.disposition(...)}/>  // no-op, just sleeps
<CallbackModule onSave={... => mockDesktopService.scheduleCallback(...)}/>  // no-op, just sleeps
```
`DispositionModule.tsx`'s save button is literally labeled **"Save mock disposition"** in the JSX. `SupervisorModule.tsx` renders a badge reading **"Read-only mock"**. None of `load/saveNotes/disposition/scheduleCallback` make an HTTP call — they `await pause()` (a fake 180 ms `setTimeout`) and return.

**This means: none of Step 4's "Disposition/notes/callback saved → Odoo CRM record updated" loop is implemented in the shipped agent desktop.** The CRM panel an agent sees is not connected to Odoo at all.

## What IS real in the agent desktop

- `src/phone.ts` (`SipJsPhone`) — a genuine SIP.js-based WebRTC phone state machine: `PROVISIONING, CONNECTING, REGISTERING, DIALING, DISCONNECTING, RECONNECTING, REGISTERED, DISCONNECTED, EXPIRED, REVOKED, ERROR`. ICE servers are pulled from the session response (`session.ice_servers`), not hardcoded.
- `src/realtime.ts` (`RealtimeClient`) — a real reconnecting WebSocket client with states `Disconnected | Connecting | Connected | Reconnecting` and exponential-style retry scheduling (`scheduleReconnect`). This satisfies Step 6's "reconnect behavior if the WebSocket disconnects" requirement.
- **Screen pop is real**: `App.tsx` listens for `event.type === "call.ringing"` on the realtime channel and renders an "Incoming call" panel with caller name/phone/campaign and a deep link `\`/web#id=${lead_id}&model=crm.lead&view_type=form\`` back into the real Odoo lead form. This is genuine, working code — the ringing-event → popup → Odoo-record-link chain exists (though the popup's *own* displayed data still comes from the mock CRM load in this build, so what the agent sees inside the popup itself is not verified to reflect the real caller — only the deep link target is real).
- `app/core/realtime.py` (middleware side): events carry a `business_unit` field and are filtered by scope (`event.business_unit != scope.business_unit` → dropped) — this is real tenant-isolation enforcement on the event fan-out path, not just a schema field. Good finding.

## Agent session / ACD state model (Step 7)

Two separate state concepts exist, and neither is the full 10-state mission model:
- **SIP/registration state** (`phone.ts`): 11 states — registration lifecycle, not ACD presence.
- **ACD presence state** (`src/types/desktop.ts`): `AgentStatus = "Ready" | "On Call" | "After Call" | "Paused"` — only 4 values. Missing as distinct states: `OFFLINE`, `LOGIN`, `RINGING`, `HOLD`, `TRANSFER`, `WRAPUP` (collapsed into "After Call"?), `DISPOSITION`, `LOGOUT`.
No code was found that maps an Odoo user → VICIdial user → extension → campaign → group at session-start time (the only campaign/endpoint values found are the hardcoded `TRANSFER_TEST`/`6197` in `webphone.py`) — this mapping, if it exists, was not located in this pass and should be treated as UNVERIFIED/likely-missing rather than confirmed absent, since VICIdial-side user/phone mapping was audited separately (see `06_VICIDIAL_ASTERISK.md`).

## Findings

**AGENT-01 (P0)** — Component: Agent Desktop / CRM data integrity. The shipped agent-desktop's disposition, notes, and callback-scheduling actions (`mockDesktopService.disposition/saveNotes/scheduleCallback`) are no-ops that never call any backend — they cannot update Odoo under any circumstance, not even if every kill-switch env var were flipped to `true`. Expected: disposition/notes/callback persist to Odoo CRM (mission Step 4, explicit requirement). Current: UI reports success ("Save mock disposition" completes, presumably shows a success toast) while silently discarding the data. Risk: **this is a false-success UX pattern** — an agent believes they saved a disposition; nothing was saved; the lead record is never updated; compliance/audit trail is empty. This is P0 because it's a live-system-danger class issue (silent data loss presented as success) that would still bite even after other flags are enabled, unless someone catches this specific file. Files: `/opt/codestra/agent-desktop/src/services/desktop.ts`, `src/App.tsx:142-144`, `src/features/disposition/DispositionModule.tsx:2`. Fix: replace `mockDesktopService` with a real service calling the middleware/Odoo APIs (there is currently no such API surface found for disposition-save from the desktop — see AGENT-02). Test: write an integration test that dispositions a call and asserts the CRM lead record's `x_last_call_disposition` changed. Rollback: n/a (this is the current broken state; fixing it is the change). Repo: agent-desktop source lives under the `codestra-middleware` GitHub repo per image labels — confirm exact path in 03_GITHUB_RUNTIME_RECONCILIATION. Suggested branch: `fix/agent-desktop-real-disposition-api`.

**AGENT-02 (P0)** — Component: Middleware / click-to-call. No API endpoint exists anywhere in the middleware (`control.py`, `telephony.py`, `webphone.py`, `orchestration.py`) that originates a call from a CRM record, and no corresponding action exists in the Odoo `crm.lead` model. Expected (mission Step 5, explicit acceptance requirement): "Verify an Odoo agent can open a lead/contact/opportunity/customer/ticket and click a phone button." Current: this feature does not exist in code, not merely disabled by a flag. Risk: Step 5 and the outbound leg of Step 23's acceptance matrix cannot pass; this is a core mission acceptance requirement, not an edge case. Files: searched `app/api/v1/*.py` (all 12 files), `codestra_vicidial_crm/models/crm_lead.py`. Fix: design and implement a `/calls/originate` (or similar) middleware endpoint with auth, campaign-permission check, E.164 validation, idempotency key, correlation ID, and a corresponding Odoo button/action calling it. Test: new integration test placing a call through this endpoint against a VICIdial staging campaign (with `ALLOW_LIVE_CALLS` still false — verify it correctly no-ops/fails-closed rather than silently succeeding). Rollback: n/a (net-new feature). Repo/branch: `feat/click-to-call-endpoint`.

**AGENT-03 (P1)** — Component: WebRTC session provisioning / multi-agent scaling. `CAMPAIGN="TRANSFER_TEST"` and `ENDPOINT="6197"` are hardcoded in `webphone.py`, so every agent who provisions a webphone session gets the identical campaign and SIP extension regardless of identity. Expected: agent → permitted campaign/queue/extension mapping (mission Step 4). Current: single shared test endpoint for everyone. Risk: this cannot support more than one concurrent real agent even if enabled; also a security/isolation concern (all agents share one extension identity). Files: `middleware/app/api/v1/webphone.py:32-34`. Fix: derive campaign/endpoint from the authenticated identity (there's already a `_odoo_identity`/`_keycloak_user` lookup in the same file — extend it to resolve per-agent extension assignment instead of using the module-level constants). Test: two distinct authenticated agents provisioning concurrently get distinct `authorization_username`/`permitted_call_scope`. Rollback: revert to constants (not recommended). Repo/branch: `feat/per-agent-extension-mapping`.

**AGENT-04 (P2)** — Component: Agent session state model. The ACD presence state (`AgentStatus`) only models 4 of the mission's 10 required states (missing `OFFLINE`, `LOGIN`, `RINGING`, `HOLD`, `TRANSFER`, `WRAPUP`, `DISPOSITION`, `LOGOUT` as distinct states). Risk: supervisor visibility and reporting will be coarse/inaccurate versus the intended model; transfer/hold can't be distinguished from generic "on call" in the UI layer. Files: `/opt/codestra/agent-desktop/src/types/desktop.ts:1`. Fix: expand the type and wire it to real ACD events once AGENT-01/02 are addressed (state model is moot while the panel is mocked). Repo/branch: `feat/full-acd-state-model` (bundle with AGENT-01 fix).

**AGENT-05 (P3)** — Component: Screen-pop data source. The inbound screen-pop panel correctly triggers off a real `call.ringing` realtime event and deep-links to the correct Odoo lead, but the customer name/phone/campaign shown inside the popup component tree still flows through the same mocked `data` object as the rest of the CRM panel in this build — not independently confirmed to reflect the real caller's data at render time. Files: `App.tsx:47,56,129`. Fix: once AGENT-01 lands, verify screen-pop payload comes from the live `call.ringing` event's own payload (it appears to already reference `screenPop.payload.customer_name` / `.phone` — likely fine — but flag for explicit verification since the surrounding panel is mocked). Test: manual/automated check that popup content matches the live WebSocket event payload, not `mockDesktopService`.

## Evidence for End-to-End Call Flow (feeds Step 23)

| Stage | Status | Evidence |
|---|---|---|
| Odoo login → identity validated | UNVERIFIED | Keycloak issuer configured; interactive flow not exercised |
| Telephony session init (WebRTC provision) | IMPLEMENTED | `webphone.py` issues scoped, short-TTL SIP credentials; `SipJsPhone` registers |
| Agent→campaign/queue/extension mapping | PLACEHOLDER | Hardcoded single campaign/endpoint (`TRANSFER_TEST`/`6197`), not per-agent |
| Ready/Paused state | PARTIAL | UI toggle exists (`AgentStatus`) but incomplete state coverage (AGENT-04); not wired to real backend confirmed |
| **Outbound click-to-call from Odoo/CRM record** | **MISSING** | No endpoint, no Odoo action method exists (AGENT-02) |
| Inbound call → screen pop in Odoo | **IMPLEMENTED** (popup+deep-link mechanism) | Real `call.ringing` WebSocket handler + Odoo deep link (App.tsx:56,129) |
| Odoo displays call state in real time | PARTIAL | Realtime WebSocket client is real and reconnecting; specific call-state UI beyond ringing/screen-pop not verified |
| Agent handles call (mute/hold/DTMF/transfer) | UNVERIFIED (phone.ts models RINGING/DIALING/etc. registration states; explicit hold/DTMF/transfer UI controls not located in this pass) | `phone.ts`, `PhoneModule.tsx` |
| Disposition/notes/callback saved | **PLACEHOLDER/BROKEN** | `mockDesktopService` — literally a no-op (AGENT-01) |
| Odoo CRM record updated | **MISSING** (follows from above — nothing calls back into Odoo from the desktop) | same as above |
| Recording metadata associated | MISSING | `codestra_vicidial_recording` module uninstalled (see 04_ODOO_READINESS ODOO-02) |
| Events distributed through middleware | PARTIAL/IMPLEMENTED for the ringing-event path | `app/core/realtime.py` business-unit-scoped event fan-out is real |

**Bottom line for Step 23's outbound and inbound journeys: outbound click-to-call is MISSING entirely (no code path exists); inbound screen-pop's notification/popup mechanism is IMPLEMENTED and is the strongest working piece of the whole agent experience, but the loop back into Odoo (disposition → CRM update) that both journeys terminate in is BROKEN by design (mock service).**
