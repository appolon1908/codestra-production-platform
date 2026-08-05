# Telephony test record

Section 1 tests passed: service health, signed adapter readiness, default-deny
firewall inspection, loopback-only database/AMI, backup encryption, local and
off-server checksums, isolated database/config restore, and health timers.

Section 2 offline tests: 34 passed. Domain tests validate aware UTC events,
tenant/workspace requirements, idempotency keys and extension allocation.
Asterisk loaded endpoint 6101 and the isolated echo context after controlled
module reload with zero active calls. Two local-only canaries were originated;
the first proved the 120-second absolute timeout and required explicit teardown
of its Echo leg, and the second produced a valid mono 8 kHz PCM WAV header.
Both ended with zero active Asterisk/VICIdial calls.

The remaining VICIdial agent, dial, callback, disposition, transfer,
middleware delivery, duplicate delivery, worker restart and reconnect
acceptance suite was operator-attested PASS on 2026-08-05. The operator
explicitly confirmed that this was the complete Section 2 acceptance test.
No production customer call was attempted by this implementation session.

```text
PRODUCTION_CUSTOMER_CALL_COUNT=0
INTERNAL_LAB_CALL_COUNT=2
UNAUTHORIZED_CALL_COUNT=0
UNAPPROVED_NUMBER_CALL_COUNT=0
SECTION_2_OPERATOR_ACCEPTANCE=PASS
```
