# Deterministic VICIdial to Odoo outcome mapping

This contract is evaluated by middleware after validating the canonical event.
VICIdial's `status` column is six characters, so long business names are
canonical outcomes rather than literal database values. Unknown values are
quarantined and never change an Odoo stage.

| VICIdial code | Canonical outcome | Odoo disposition | Odoo stage | Activity | Callback/retry | DNC | Required note | Audit event | Idempotency |
|---|---|---|---|---|---|---|---|---|---|
| `SALE` | `SALE` | `qualified_sale` | `qualified_sale` | Close current call activity as successful | No retry; cancel open call retries | Preserve any existing suppression | Sale result and VICIdial correlation ID | `telephony.outcome.sale` | One stage transition per canonical event ID |
| `CALLBK`, `AICB` | `CALLBACK` | `callback_requested` | No stage change | Upsert one callback activity with UTC due time | Retry eligible only at callback time; reschedule replaces the prior due time | Preserve | Callback time, timezone and assigned owner | `telephony.outcome.callback` | One open callback per lead and callback correlation ID |
| `B`, `AB` | `BUSY` | `busy` | No stage change | Close attempt as busy | Controlled retry under campaign attempt policy | Preserve | Attempt number and next eligible time | `telephony.outcome.busy` | One attempt per canonical event ID |
| `N`, `NA` | `NO_ANSWER` | `no_answer` | No stage change | Close attempt as no answer | Controlled retry under campaign attempt policy | Preserve | Attempt number and next eligible time | `telephony.outcome.no_answer` | One attempt per canonical event ID |
| `NI`, `AINI` | `NOT_INTERESTED` | `not_interested` | `closed_not_interested` | Close open call/callback activities | No automatic retry | Preserve | Agent-selected reason when present | `telephony.outcome.not_interested` | Terminal transition is monotonic |
| `DNC`, `DNCC`, `DNCL`, `AIDNC` | `DNC` | `do_not_contact` | `closed_do_not_contact` | Cancel all call and callback activities | Never retry | Set permanent phone/contact suppression; adapter cannot remove it | Source, actor, timestamp and policy basis | `telephony.outcome.dnc` | First suppression wins; repeats are acknowledgements |
| `BADNUM`, `AIWN` | `WRONG_NUMBER` | `wrong_number` | No stage change | Close current call activity | No retry for this number; other consented numbers unaffected | Preserve | Masked invalid-number reference | `telephony.outcome.wrong_number` | One invalidation per normalized phone hash |
| `DC`, `ADC` | `DISCONNECTED` | `disconnected_number` | No stage change | Close current call activity | No retry for this number | Preserve | Carrier/VICIdial disconnect classification | `telephony.outcome.disconnected` | One invalidation per normalized phone hash |
| `PU` | `ANSWERED` | `answered` | No stage change | Close attempt as answered | No automatic retry unless a later explicit disposition allows it | Preserve | Duration and agent/correlation identifiers | `telephony.outcome.answered` | Never implies a sale |
| `XFER`, `AIXFER`, `RQXFER` | `TRANSFER` | `transferred` | No stage change | Close originating activity and create/upsert transfer follow-up | Retry only when the transfer policy returns an explicit failure | Preserve | Allowlisted destination identifier and transfer outcome | `telephony.outcome.transfer` | One transfer result per transfer correlation ID |
| `APPT` | `APPOINTMENT` | `appointment_set` | `appointment_scheduled` | Upsert appointment activity with UTC start and owner | Reschedule updates the same appointment; no duplicate activity | Preserve | Appointment time, timezone, owner and result | `telephony.outcome.appointment` | One appointment per appointment correlation ID |

## Ordering and conflict rules

- `DNC` is terminal and cannot be reversed by telephony events.
- `SALE`, `NOT_INTERESTED`, and `DNC` cannot be regressed by an older event.
- `ANSWERED` never implies `SALE`.
- Events with an earlier source timestamp may add audit evidence but cannot
  regress stage, suppression, callback, or appointment state.
- A reused idempotency key with a different payload is a conflict and produces
  no Odoo mutation.
- Middleware acknowledges success only after its PostgreSQL event record and
  outbox operation are durable.
