# Codestra CRM Call Follow-up API

This optional Odoo 19 addon hardens the completed-call RPC boundary without adding
a public HTTP controller.

## RPC model

`codestra.crm.call.followup`

## Methods

- `register_completed_call_v1(payload)`
- `validate_completed_call_v1(payload)`
- `get_completed_call_status_v1(company_id, event_id)`
- `get_integration_capabilities()`

Only the dedicated `Call Follow-up / Integration Service` group may call these
methods. Use an Odoo API-key identity, HTTPS through the approved private gateway,
bounded timeouts, and the same `event_id` for retries.

A repeated `(company_id, event_id)` with the same immutable payload is returned as
a replay. A repeated key with a different immutable payload is rejected.
