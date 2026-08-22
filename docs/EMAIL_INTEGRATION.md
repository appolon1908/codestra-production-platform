# Email integration

Klyrow is the sole email adapter; middleware never calls Postal or Mautic internals. Addresses are normalized, classification is mandatory, marketing requires positive consent, and middleware suppression is authoritative. Hard bounce, complaint, and unsubscribe create suppression; complaints and unsubscribes revoke consent. Raw states remain beside normalized states.

`KLYROW_MODE=test` returns synthetic accepted IDs without external delivery. Production requires both global authorization gates, a distinct Klyrow credential, private URL, authorized sender/domain and destinations, plus completed SPF/DKIM/DMARC/PTR/TLS and deliverability review.

## Inbound Postal contract

Postal submits RFC 822 messages to
`POST /api/v1/integrations/postal/inbound` as an authenticated, timestamped and
signed envelope. `POSTAL_INBOUND_ENABLED` defaults to `false`; enabling the
endpoint is a separate governed production action.

The middleware resolves one exact active mailbox and campaign, claims the
provider event in a durable inbox, rejects event-ID reuse with different
content, and preserves Message-ID, In-Reply-To, References, correlation ID and
provider event ID. Attachments are allowlisted, size-limited, scanned through
clamd and written to tenant-scoped protected storage. Non-clean results are
quarantined and never projected. Odoo receives only the validated projection
through a signed HTTP contract and must echo the immutable routing/threading
fields as read-back.

Required secret/config references are `POSTAL_MIDDLEWARE_API_KEY[_SHA256]`,
`POSTAL_WEBHOOK_SECRET`, `POSTAL_CLAMD_HOST`, `POSTAL_OBJECT_STORE_URL`,
`POSTAL_OBJECT_STORE_TOKEN_FILE`, `POSTAL_ODOO_INBOUND_URL`, and
`POSTAL_ODOO_HMAC_SECRET_FILE`. Secrets never belong in Git or workflow
exports. Any unavailable scanner, object store or Odoo projection fails closed.
