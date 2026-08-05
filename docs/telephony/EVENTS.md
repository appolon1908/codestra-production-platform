# Telephony events

The passive AMI gateway maintains a durable local outbox. External delivery is
disabled until authenticated middleware delivery testing. The canonical event
model requires UUID event ID, event type/version, tenant/workspace, optional
campaign/call/agent/lead IDs, UTC timestamp, correlation ID, idempotency key
and bounded payload.

Supported lifecycle names include call start/ring/answer/agent-connect/
disposition/transfer/end, recording ready, callback request/completion, agent
login/ready/pause/logout, and campaign start/pause/stop. Duplicate keys must
return the original result rather than publish twice.

