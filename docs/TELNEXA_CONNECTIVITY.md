# Telnexa Connectivity

Outbound SMS used simulator behavior only. A synthetic transactional message to `+10000000000` was accepted, became `simulator_accepted`, replayed to the same message, and was read back. Evidence records `carrier_or_bulk_submitted=false`.

Private `inbound`, `dlr`, `failure`, and `provider-status` routes accepted signed synthetic events and rejected replay. The control plane normalized a delivered callback. Missing/invalid bearer, invalid HMAC, and stale timestamp were rejected.

Middleware -> Telnexa: PASS in simulator. Telnexa -> Middleware: PASS with signed synthetic callbacks. Real carrier/Jasmin submission was not attempted.
