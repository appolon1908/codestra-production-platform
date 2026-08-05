# Communication channels

Supported channel values are VOICE, EMAIL, SMS, WHATSAPP,
FACEBOOK_MESSENGER, INSTAGRAM_DIRECT, TELEGRAM, WEB_CHAT, INTERNAL_CHAT,
VIDEO_MEETING and PUSH_NOTIFICATION.

Core logic contains no provider-specific business rule. Each channel account
has an approved sender identity, tenant/workspace ownership, rate limit,
template policy, conversation-window policy and health state. Email mailbox
access is scoped; SMS/WhatsApp support consent, opt-out, templates, receipts
and media; social adapters prohibit bulk outreach. Web chat always reaches AI
through middleware. Meeting interfaces reference external providers rather
than implementing a custom media server.

