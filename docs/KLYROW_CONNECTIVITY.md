# Klyrow Connectivity

Outbound safe evidence: `KLYROW_MODE=test` returns a unique `test-*` ID with no external delivery. Production requires both global authorization and a private URL/token.

Inbound evidence: delivered/bounced/complained/unsubscribed normalization, HMAC freshness, replay dedupe, suppression, consent revocation, and duplicate message-event prevention pass locally. Production Postal/Mautic queues, sender DNS, PTR, deliverability, and callback credentials remain BLOCKED by runtime access.
