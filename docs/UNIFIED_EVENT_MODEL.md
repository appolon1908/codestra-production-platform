# Unified event model

Provider ingress authenticates the source key and HMAC-SHA256 over timestamp, event ID, source, and exact body. Timestamps expire after 300 seconds by default. The normalized envelope carries event/type/version/time, correlation and causation IDs, tenant/customer/message/channel, source/provider, request/idempotency identifiers, payload, and metadata.

Inbox uniqueness prevents repeated webhook effects. Each accepted transition appends an immutable message timeline event. Governed delivery forwards normalized envelopes to approved Odoo or n8n endpoints with correlation preserved; bounded retry ends in durable dead-letter state.
