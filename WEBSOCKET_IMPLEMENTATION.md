# WebSocket Implementation

- Gateway commit: `52fe91ed49723c43b3ffd8910a4affdea1a66065`
- Agent Desktop commit: `4063a08d90fbb777cd74b68f7dd749e389a115f2`
- Gateway image: `codestra/websocket-gateway@sha256:76f0ca029e59f36dc7b70d5784930608a6036dcaa0dfde22ad0a343192381dc0`
- Gateway container: `df4ca04a61a301bf20ac40b69ef66fdb5cc17e42c6aa9135e48f7e05762c39a8`
- Desktop image: `codestra/agent-desktop@sha256:fefd25c403c616f169cc6f1ebdb67bcfc8b0b4179da604d6805fc40c72cb9f29`
- Desktop container: `67df9a6c547b83bc35e0657d642d974015a001a0c977e1a07b5fffa8566a40a0`

The gateway is non-root UID 10001, read-only, `no-new-privileges`, all capabilities dropped, resource-limited, healthchecked, and not host-published. The Desktop is also read-only/non-root/capability-free. Startup clears stale process-local ownership flags without deleting durable sessions or events. The reusable Desktop client owns connect/disconnect, deduplication, cursor persistence, reconnect backoff, call/recording handlers, and independent Phone/Realtime indicators.

