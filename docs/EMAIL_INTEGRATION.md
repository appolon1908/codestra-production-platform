# Email integration

Klyrow is the sole email adapter; middleware never calls Postal or Mautic internals. Addresses are normalized, classification is mandatory, marketing requires positive consent, and middleware suppression is authoritative. Hard bounce, complaint, and unsubscribe create suppression; complaints and unsubscribes revoke consent. Raw states remain beside normalized states.

`KLYROW_MODE=test` returns synthetic accepted IDs without external delivery. Production requires both global authorization gates, a distinct Klyrow credential, private URL, authorized sender/domain and destinations, plus completed SPF/DKIM/DMARC/PTR/TLS and deliverability review.
