# Klyrow Connectivity

Outbound email used Klyrow test mode and `recipient@audit.invalid`. It became `test_accepted`, replayed idempotently, and was read back. No SMTP/provider delivery was attempted.

Private `campaigns`, `contacts`, `events`, `bounces`, `complaints`, and `unsubscribes` routes accepted signed events and rejected replay. The control plane normalized a delivered callback. Missing/invalid bearer, invalid HMAC, and stale timestamp were rejected.

Middleware -> Klyrow: PASS in safe/test mode. Klyrow -> Middleware: PASS with signed synthetic callbacks. No local Mautic/Postal process or usable remote Klyrow deployment identity was found.
