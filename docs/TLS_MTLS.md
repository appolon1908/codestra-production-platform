# TLS and mTLS

| Path | Mode | Live evidence | Result |
|---|---|---|---|
| Middleware -> `authorization.internal.codestra.agency:8443` | mTLS/private CA | health and ready 200; missing client cert terminated | PASS |
| Peer -> `middleware.internal.codestra.agency:443` | mTLS/private CA/source restriction | private bind; Caddy requires verified client cert | PASS config; reverse callback not locally initiated |
| Public `crm/api/n8n/auth.codestra.agency` | ordinary TLS intended | correct DNS; TCP/HTTPS unreachable | FAIL |

Private CA: 2026-07-22 to 2036-07-19. Middleware client: through 2027-08-23 with SPIFFE URI SAN. Middleware server: DNS SAN `middleware.internal.codestra.agency`, through 2027-08-23. Remote adapter: SANs `authorization.internal.codestra.agency` and `edge.internal.codestra.agency`, through 2027-08-23.

Remote health is timer-monitored. A complete private-certificate auto-renew/reload timer was not observed; owner action is required before expiry. Keys remain 0600/0640 and were never printed.
