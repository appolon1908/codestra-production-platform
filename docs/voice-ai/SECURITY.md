# Voice AI security

Tests cover media authentication, signature tampering, expiry, replay,
cross-tenant context, call ID, extension/number allowlists, prohibited AI
actions, barge-in buffer disposal and 50 synthetic English/Spanish fixtures.
Prompt-injection and malicious-metadata fixtures are treated as untrusted text,
never tool authorization.

Recording/transcript access must evaluate tenant, workspace, department,
campaign, agent/supervisor/QA role, customer scope, retention and legal hold.
Only middleware returns permission-controlled references.

The AI host accepts TCP/22 but rejected all available SSH identities; no
Whisper, Qwen or TTS runtime port was reachable. Consequently live streaming,
latency, outage and Odoo synchronization gates are not claimed as passed.

