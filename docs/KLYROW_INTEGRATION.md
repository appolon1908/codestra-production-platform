# Klyrow integration

Klyrow events use the private vSwitch and dedicated API/HMAC credentials. Middleware accepts queued, sent, delivered, bounced, complained, opened, clicked, unsubscribed, and campaign lifecycle events, preserves correlation, updates consent/suppression, then invokes approved Odoo/n8n adapters. Outbound email flows through middleware to Klyrow, never Postal internals. Safe mode remains required until mail DNS/PTR/TLS gates pass.
