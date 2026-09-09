# WebSocket latency evidence

The certifier requires 250 distinct authorized tenant/campaign/agent scopes,
one open socket per scope and one measured canonical JetStream event per
socket. Each received event must match its event ID, scope and acknowledged
stream cursor. Timeouts, malformed frames and missing deliveries fail the run
rather than being excluded from its samples.

Latency starts before publication and ends after both PubAck and the matching
WebSocket delivery. The report uses nearest rank `ceil(0.95 * N) - 1`, retains
the sample count and maximum, and fails at p95 >= 500 milliseconds. Connection
time and the legacy internal-HTTP screen-pop smoke are reported separately.
An HTTP injection result does not certify the JetStream path.

All tests in this source change use fakes or local fixtures. The certifier was
not run against a server. Its full execution requires separately authorized
isolated staging identities, broker permissions and source/runtime bindings;
no production or external-effect authorization is supplied here.
