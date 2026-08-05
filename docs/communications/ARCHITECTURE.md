# Unified communications architecture

Middleware owns conversations, participants, messages, events, channel
accounts, threads, attachments, delivery attempts, receipts, typing,
escalations, assignments and audit events. Every row is tenant/workspace
scoped. Odoo remains the authoritative business timeline; channel providers
are delivery systems, never customer authorities.

The VICIdial host contributes only VOICE operational events and recording
metadata. It does not host customer identity resolution, outbound messaging
approval or provider credentials. Provider-neutral adapters implement health,
approved send and delivery-state reads. Initial email, SMS, WhatsApp, social,
web chat, internal chat, meeting and push behavior is staging-only.

The middleware API contract is:

```text
GET  /api/v1/communications/conversations
GET  /api/v1/communications/conversations/{conversation_id}
POST /api/v1/communications/conversations/{conversation_id}/assign
POST /api/v1/communications/messages
POST /api/v1/communications/messages/{message_id}/approve
POST /api/v1/communications/messages/{message_id}/cancel
GET  /api/v1/communications/channels
GET  /api/v1/communications/health
```

