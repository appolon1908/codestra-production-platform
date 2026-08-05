# Transfers

Warm, cold, queue, supervisor and approved external transfers are modeled.
Destinations require a tenant/campaign allowlist. Arbitrary-number transfer is
disabled. Audit records contain call ID, source agent, destination, type,
start/end, result/failure and recording reference.

Extension 6101 has `allow_transfer=no` and its isolated context contains no
transfer application or outbound route.

