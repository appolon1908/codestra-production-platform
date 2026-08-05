# Voice AI architecture

Asterisk/VICIdial owns calls. A private authenticated media bridge carries
audio and bounded call context to `5.9.108.250`. Middleware at `65.109.65.169`
supplies customer context, permissions, tool authorization, approvals, Odoo
synchronization and audit. The AI runtime owns VAD, Faster-Whisper, Qwen,
retrieval, TTS and barge-in reasoning only.

No AI component can activate campaigns, call arbitrary numbers, transfer to an
unapproved destination, modify trunks/carriers, accept payment, issue refunds,
change contracts, trade, or make medical/legal decisions. All Odoo writes pass
through middleware.

