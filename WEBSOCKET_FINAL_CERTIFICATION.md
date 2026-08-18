# WebSocket Final Certification

Certified `2026-08-17T20:32:18-04:00` on Server A; evidence commit `c99a5ca`. Public TLS certificate CN/SAN is `api.codestra.agency`, issued by Let's Encrypt, valid 2026-07-20 through 2026-10-18. Health and readiness passed, including database, authentication configuration, realtime state backend, and middleware event source. n8n remained healthy with zero realtime-path calls.

Functional/security/browser/recovery/load gates all passed. Evidence lives under `evidence/websocket-gateway-20260817/`.

The images were built locally and have no same-run CI workflow/build ID, SBOM digest, scan identity, signature/attestation, registry publication, pull-by-digest verification, or approval bound to their digests. Under the repository's immutable OCI provenance rule, `EXACT_ARTIFACT_PROVENANCE_GATE=FAIL`. In addition, this run validated synthetic middleware-boundary publication but did not originate a real synthetic endpoint-6101 call on Server B through the restricted adapter. The required Asterisk/VICIdial-to-browser chain is therefore not end-to-end certified.

`WEBSOCKET_GATEWAY_INSTALLED=PASS`  
`WEBSOCKET_HEALTH=PASS`  
`WEBSOCKET_READY=PASS`  
`TLS_WSS=PASS`  
`KEYCLOAK_AUTH=PASS`  
`REALTIME_TICKET_ISSUANCE=PASS`  
`TICKET_SINGLE_USE=PASS`  
`AGENT_SESSION_BINDING=PASS`  
`TENANT_BINDING=PASS`  
`CAMPAIGN_BINDING=PASS`  
`SCREEN_POP_WEBSOCKET=PASS`  
`RECORDING_WEBSOCKET=PASS`  
`CROSS_AGENT_ISOLATION=PASS`  
`CROSS_TENANT_ISOLATION=PASS`  
`WRONG_CAMPAIGN_ISOLATION=PASS`  
`DUPLICATE_EVENT_PROTECTION=PASS`  
`RECONNECT=PASS`  
`REPLAY_AFTER_RECONNECT=PASS`  
`MIDDLEWARE_RESTART_RECOVERY=PASS`  
`PROXY_RESTART_RECOVERY=PASS`  
`LOAD_TEST=PASS`  
`P95_DELIVERY_LATENCY=PASS`  
`BROWSER_TEST=PASS`  
`ROLLBACK_READY=PASS`

`CODESTRA_WEBSOCKET_GATEWAY=BLOCKED`

Exact blockers: (1) immutable CI artifact provenance and approval are absent for gateway digest `sha256:76f0ca029e59f36dc7b70d5784930608a6036dcaa0dfde22ad0a343192381dc0` and Desktop digest `sha256:fefd25c403c616f169cc6f1ebdb67bcfc8b0b4179da604d6805fc40c72cb9f29`; (2) an endpoint-6101 synthetic call traversing Server B, the restricted adapter, middleware, durable persistence, and the deployed browser was not executed in this run.
