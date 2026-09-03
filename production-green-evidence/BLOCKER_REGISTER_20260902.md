# Blocker register — 2026-09-02

| Severity | Gate | Evidence | Safe next action |
|---|---|---|---|
| Critical external | GitHub Actions allocation for Codestra-SRL | Canonical Middleware convergence PR #283 exact head `e48ec614a2da680802ee106e271b52f3006e72dc`; runs `33667817256`, `33667811315`, and `33698014234` failed before job assignment | Restore Actions allocation, rerun exact-head CI, and merge only after every required check reports success |
| High | Required business API and runtime attribution certification incomplete | Health/readiness/version/capability/OpenAPI/gateway/runtime-attribution matrices remain unproven | Complete endpoint inventory, source/runtime OpenAPI alignment, gateway mapping, authorization negatives, and exact runtime revision/digest attribution before later waves |
| High | Waves 4–5 incomplete | Mail API, email reseller, and reseller portal passed controlled replacement, but webhook and remaining provider/runtime workloads are unchanged | Continue only after canonical Middleware #283 and remaining source-lock gates pass |
| High | Email-reseller metrics contract incomplete | Protected runtime is healthy, ready, attributable, and fail-closed, but `/metrics` returns 401 | Implement real bounded metrics in protected source and publish a new immutable digest before metrics certification |

```text
PRODUCTION_BUSINESS_WRITES_ENABLED=NO
EXTERNAL_BUSINESS_EFFECTS=0
ADMIN_BYPASS_AUTHORIZED=NO
OVERALL_VERDICT=NO_GO
```
