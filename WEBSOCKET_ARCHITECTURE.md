# WebSocket Architecture

`Asterisk/VICIdial (Server B) -> restricted adapter -> middleware (Server A) -> durable realtime PostgreSQL -> codestra-websocket-gateway -> authorized Agent Desktop`.

The browser separately connects to Asterisk WSS for SIP/WebRTC. The Codestra socket carries JSON application state only and never RTP/audio. Caddy terminates TLS and proxies `/ws/agent` plus the HTTPS ticket endpoint. Identity is resolved from a Keycloak access token; the socket receives an opaque, hashed-at-rest, 45-second, single-use ticket in its first frame. Server-side scope binds user, tenant, business unit, agent, VICIdial user, extension, campaigns, and session.

Events are persisted before delivery. Replay selects only the bound scope after `last_event_id`. Event IDs and `(tenant, call, sequence)` constraints provide idempotency. Uvicorn supplies 25-second ping/10-second timeout heartbeat; bounded queues, message size, and write timeout protect memory.

`REALTIME_N8N_DEPENDENCY=NONE`

