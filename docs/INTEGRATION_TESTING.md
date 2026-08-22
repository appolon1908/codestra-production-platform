# Integration Testing

Run:

```bash
scripts/full-connectivity-audit.sh
```

It writes `artifacts/connectivity-audit.json`, runs inside deployed containers so secrets never leave their boundary, and uses unique synthetic IDs, a reserved phone number, and `.invalid` email addresses. It never submits to a carrier or email provider.

It validates every control-plane identity and private-gateway route, positive/negative bearer auth, valid/invalid/stale HMAC, replay, idempotency conflict, correlation lookup, Telnexa simulator and DLR read-back, Klyrow test dispatch and callback read-back, metrics, and operator rejection.

Latest: **93 PASS, 0 FAIL** (`20260815T130649Z-c629903b`). Repository suite: **192 tests and 9 subtests PASS**. This proves deployed local paths only; absent workers, credentials, provider accounts, and workflows remain FAIL/BLOCKED.
