# WebSocket Security Tests

Public-path synthetic certification passed:

- expired/invalid JWT: 401
- required Keycloak roles and mapped agent claims: PASS
- ticket TTL 30–60 seconds and single use: PASS
- missing auth: close 4408; invalid ticket: close 4401
- origin allowlist: enforced; wildcard absent
- agent, tenant, business-unit, user, and campaign scope: server-controlled
- cross-agent delivery: denied
- cross-tenant delivery: denied
- wrong campaign delivery: denied
- duplicate event delivery: denied
- client-selected subscriptions: unsupported
- secrets and PII excluded from metric labels; access-token headers are redacted by Caddy

`CROSS_AGENT_ISOLATION=PASS`  
`CROSS_TENANT_ISOLATION=PASS`  
`WRONG_CAMPAIGN_ISOLATION=PASS`  
`WEBSOCKET_TICKET_REPLAY=PASS`

