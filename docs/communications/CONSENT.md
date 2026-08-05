# Consent and identity

Consent records carry channel, purpose, customer, state, source, effective and
expiry/withdrawal timestamps, and an evidence reference. Denied, withdrawn or
expired consent and explicit opt-out force outbound messages to BLOCKED or
CANCELLED. Delivery states beyond draft/approval require an approval reference.

Identity matching uses normalized phone, email or provider subject. Exactly one
deterministic match may return MATCHED; duplicate exact matches return
MULTIPLE_MATCHES and cannot merge automatically. Probabilistic matches require
review. Cross-tenant lookups are impossible through the tenant-keyed store.

