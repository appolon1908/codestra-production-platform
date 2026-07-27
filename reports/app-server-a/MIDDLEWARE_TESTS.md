# Middleware Tests

Verified UTC: 2026-07-27.

| Test | Result | Evidence |
|---|---|---|
| Existing repository suite | PASS | 78 tests and 9 subtests before changes |
| Full suite after design implementation | PASS | 94 tests and 9 subtests |
| Disabled-by-default manifest | PASS | All generated mutation flags false |
| Preview idempotency | PASS | Identical replay returned the saved manifest |
| Changed replay conflict | PASS | Reused UUID with changed input rejected |
| Concurrent allocation | PASS | 24 concurrent allocations, 24 unique IDs |
| Staging isolation | PASS | Allocation began at 91000 |
| Production BU allocation | PASS | COD allocation began at 21000 |
| Peer adapter health | BLOCKED | Port 9443 unreachable; HTTPS contract paths 404 |

No PASS in this report asserts a deployed peer mutation or production
activation.
