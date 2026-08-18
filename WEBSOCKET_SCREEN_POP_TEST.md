# WebSocket Screen-Pop Test

An authenticated synthetic `call.ringing` event for campaign `TEST_SYN` was persisted, delivered only to `CERT-AGENT-A`, and rendered once in the deployed Desktop with `Synthetic Customer`, the correct campaign, and synthetic lead link. The browser screenshot is `evidence/websocket-gateway-20260817/browser-screen-pop-recording.png`.

The API-level run measured 17.802 ms from accepted event to browser handler path; this is below both the 500 ms delivery and 1 second screen-pop targets.

`SCREEN_POP_WEBSOCKET=PASS`

