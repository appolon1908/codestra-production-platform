# WebSocket Baseline

Captured `2026-08-17T20:32:18-04:00` on Server A (`middleware`, `65.109.65.169`, `10.40.0.1`). Discovery found the canonical middleware realtime primitives and the Server-A Agent Desktop; no application gateway was installed on Server B. The authoritative completed service is `codestra-websocket-gateway`.

- Public edge: existing Caddy on `443`; no gateway host port.
- Private dependencies: PostgreSQL, middleware health source, Keycloak JWKS, and NATS on private/loopback networks.
- n8n: healthy, but absent from gateway readiness and delivery.
- Reserved application path: `wss://api.codestra.agency/ws/agent`.
- Public health: `/healthz` and `/readyz` return healthy/ready.
- Safety: synthetic identities/events only; live dialing, callbacks, SMS, email, and transcription were not enabled.

`REUSE_AND_COMPLETE_EXISTING_GATEWAY=true`

