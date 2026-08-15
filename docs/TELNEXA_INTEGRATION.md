# Telnexa integration

Telnexa continues to use private ingress with separate credentials for inbound SMS, DLR, failures, and provider status. Middleware owns message idempotency, contact mapping, consent and STOP suppression, Odoo history, and governed n8n events. Outbound requests require a positive preference check and safe-mode/approval controls. Tests use mock provider responses only.
