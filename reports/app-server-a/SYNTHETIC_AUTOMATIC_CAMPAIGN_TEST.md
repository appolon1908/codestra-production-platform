# Synthetic automatic-campaign staging acceptance

Date: 2026-07-27
Branch: `release/production-activation`
Result: `PASS`

## Safety boundary

- Middleware used `https://edge.internal.codestra.agency:8443/restricted-vicidial`.
- The name resolved to the approved private VICIdial address `10.40.0.2`.
- Transport used the deployed private-VLAN mTLS listener and signed service requests.
- The adapter application remained bound to loopback behind the protected Apache listener.
- The adapter backend was memory-only for the bounded exercise.
- Production dialing, IVR callbacks, external communication, and public database access remained disabled.
- No customer telephone number was supplied. The only lead used a reserved synthetic non-contact placeholder.
- Preflight and postflight both showed zero live agents, auto calls, hopper rows, and active Asterisk calls.

## Lifecycle evidence

The staging control-plane test created one TEST business-unit design event, generated a canonical manifest, recorded simulated supervisor approval, reserved list `91000` atomically, and provisioned campaign `TSTE344E` disabled.

Read-back verified the disabled campaign and list. The atomic provisioning response recorded the expected user, closer and inbound groups, script and dispositions. A disabled test agent (`TST6101`) and one synthetic lead were created in memory. The n8n scope `STG-TEST-E2E-V1` remained inactive and the Odoo projection progressed to `rolled_back_disabled`.

Retrying the same campaign and lead requests returned idempotent replays. Reconciliation completed with no unexplained drift. Rollback preserved the disabled campaign state.

## Verified controls

| Control | Result |
|---|---|
| Campaign and list disabled | PASS |
| User, inbound and closer groups | PASS |
| Script and dispositions | PASS |
| Transfer policy same-campaign-only | PASS |
| n8n workflow inactive | PASS |
| Exactly-once design event | PASS |
| Idempotent campaign and lead retry | PASS |
| Full correlation and hashed audit records | PASS |
| No production dialing or external communication | PASS |
| Adapter restored to all mutation flags false | PASS |

The original adapter environment and startup validator were restored byte-for-byte after the test. Final readiness returned `writes_enabled=false`.

Runtime credentials, certificates, raw state databases, and the unredacted execution workspace are excluded from Git.
