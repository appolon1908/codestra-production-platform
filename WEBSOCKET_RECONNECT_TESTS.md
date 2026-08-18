# WebSocket Reconnect Tests

The browser recovery harness connected through public TLS, received a baseline event, stopped the gateway, durably inserted the missing authorized event, restarted the gateway, obtained a fresh ticket, and replayed the missing event exactly once. It then repeated recovery while restarting the Caddy edge.

Evidence: `evidence/websocket-gateway-20260817/recovery-results.json`.

`RECONNECT=PASS`  
`REPLAY_AFTER_RECONNECT=PASS`  
`MIDDLEWARE_RESTART_RECOVERY=PASS`  
`PROXY_RESTART_RECOVERY=PASS`  
`DUPLICATE_EVENT_PROTECTION=PASS`

