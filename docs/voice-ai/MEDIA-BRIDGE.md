# Private media bridge

Media tokens bind UUID token ID, tenant, workspace, call/session IDs, extension,
hashed approved number, issue/expiry, and maximum duration under HMAC. The
verifier rejects invalid signatures, expired/replayed tokens, tenant/workspace
mismatch, call mismatch, unapproved extensions and unapproved number hashes.

Sessions require sequence numbers, heartbeat, bounded input/output, barge-in,
disconnect, recovery, rate limits and maximum duration. Raw phone numbers are
not metric labels or token claims.

