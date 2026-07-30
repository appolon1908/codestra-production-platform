# Server B active-call protection plan

```text
MAX_ACTIVE_CALLS_FOR_CHANGE=0
MAX_ACTIVE_CHANNELS_FOR_CHANGE=0
CALL_COUNT_RECHECK_INTERVAL_SECONDS=30
MAX_IMPLEMENTATION_VALIDATION_MINUTES=15
MAX_ROLLBACK_MINUTES=10
```

Before any separately authorized Server B change, use approved read-only
Asterisk and VICIdial views to verify zero active calls and zero active
channels. Also verify queues have no callers, conferences have no participants,
manager sessions are understood, and the dialer has no active or pending
delivery. The exact commands must be reconciled against the active baseline in
the next phase; this off-host phase deliberately does not contact Server B.

Any call or channel immediately blocks the change. Never force a disconnection
to create a maintenance window. Recheck every 30 seconds throughout the
maximum 15-minute implementation validation window and abort immediately if
unexpected activity appears. Asterisk reload or restart requires separate
explicit approval. Post-change evidence must prove unchanged call identifiers,
zero affected calls, and no forced disconnection.

`BASELINE_ACTIVE_CALL_PROTECTION_PLAN_GATE=PASS`
