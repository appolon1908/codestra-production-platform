# Blocker register — 2026-09-02

| Severity | Gate | Evidence | Safe next action |
|---|---|---|---|
| Critical external | GitHub Actions billing for Codestra-SRL | Middleware PR #281 exact head `5fa44e8d1c5f1cf62d6af0b984b86b9d1740fc96`; retries failed before job assignment | Organization owner restores Actions billing/spending, reruns exact-head CI, and merges only after the required check reports success |
| High | Corrected backup authority not protected or installed | Platform PR #182; seven review findings were addressed in source and regression tests, but the changed head requires new CI and independent approval | Require exact-head CI, zero unresolved threads, independent approval, protected merge, exact protected-source installation, fresh encrypted/off-host backup, and fresh isolated restore |
| High | Required business API and runtime attribution certification incomplete | Health/readiness/version/capability/OpenAPI/gateway/runtime-attribution matrices remain unproven | Complete endpoint inventory, source/runtime OpenAPI alignment, gateway mapping, authorization negatives, and exact runtime revision/digest attribution before later waves |
| High | Waves 4–5 incomplete | Webhook worker replacement and later controlled waves have not started | Complete only after Middleware #281 and corrected database certification pass their protected gates |

```text
PRODUCTION_BUSINESS_WRITES_ENABLED=NO
EXTERNAL_BUSINESS_EFFECTS=0
ADMIN_BYPASS_AUTHORIZED=NO
OVERALL_VERDICT=NO_GO
```
