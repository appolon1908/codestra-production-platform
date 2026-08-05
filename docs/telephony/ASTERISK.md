# Asterisk core

Asterisk 18.26.4-vici runs both legacy `chan_sip` and PJSIP. Existing
`chan_sip` routing is preserved; new test endpoints use PJSIP. SRTP and secure
WebSocket support are loaded. ARI modules are installed but ARI is disabled and
has no configured users. AMI is loopback-only and the passive event account is
read-only.

Dialplan configuration is split between generated VICIdial configuration and
isolated Codestra includes. Extension 6101 uses PJSIP/WSS, DTLS-SRTP, one
contact, no transfer and the `codestra-echo-only` context. That context exposes
only extension 6000 (`Answer`, `Echo`, `Hangup`) with a 120-second absolute
timeout. It cannot reach a trunk, queue, conference or external number.

CDR/CEL, music-on-hold and recording behavior remain under VICIdial/Asterisk
configuration. No chan_sip-to-PJSIP migration was attempted.

