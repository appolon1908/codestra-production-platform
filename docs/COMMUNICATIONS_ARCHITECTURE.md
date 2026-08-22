# Communications architecture

Odoo, n8n, and internal applications call authenticated middleware on its existing private/loopback ingress. Middleware owns tenant authorization, contact identity, preferences, idempotency, ledger state, metering, audit, retry, and normalized events. SMS routes only to Telnexa and email only to Klyrow; callers cannot access Jasmin, SMPP, Mautic, Postal, Redis, RabbitMQ, or provider databases.

API and worker share WAL-mode SQLite at `/data/control-plane.db`, so messages, inbox/outbox events, usage, suppressions, retries, and audit survive restarts. Provider callbacks use separate service keys and HMAC secrets. The shared host uses private `10.40.0.2`; public provider URLs are rejected. The service remains `127.0.0.1:8096`, preserving production ingress at `10.40.0.1:8095`.

Production delivery requires outbound processing, provider production mode, production authorization, a private URL, and a channel-specific credential. Missing any gate fails closed. Telnexa simulator and Klyrow test mode are used for acceptance.
