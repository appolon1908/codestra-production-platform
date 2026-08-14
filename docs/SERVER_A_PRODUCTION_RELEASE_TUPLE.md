# Server A production release tuple authority

This document removes the source-to-runtime ambiguity between the two Server A
repositories. It is an ownership contract, not production activation.

| Element | Authority | Candidate identity | Runtime artifact |
| --- | --- | --- | --- |
| Orchestration, JetStream definitions, host policy and evidence tooling | `appolon1908-hue/codestra-production-platform` | PR 15 exact protected merge SHA | signed deployment/configuration bundle |
| Middleware executable source | `Codestra-SRL/codestra-middleware` | PR 219 exact protected merge SHA | `ghcr.io/codestra-srl/codestra-middleware@sha256:<production-approved-digest>` |
| Database migrations | canonical middleware image and its Alembic revision | read from the exact image | migration owner executes; runtime roles never own schemas |
| JetStream server contract | production-platform `eventing/jetstream_contract.json` | checksum from protected configuration bundle | applied and read back by `tools/apply_jetstream_contract.py` |
| JetStream publisher and DLQ worker | canonical middleware image | PR 219 protected merge SHA | `app.eventing.jetstream` and `app.entrypoints.jetstream_dlq_worker` |
| Keycloak contract | production-platform production identity contract plus canonical middleware runtime settings | checksums from both protected artifacts | production issuer/client only; staging identity rejected |
| Odoo and n8n integration logic | canonical middleware image | exact protected middleware SHA | versioned image digest |
| Callback adapter contract | production-platform policy plus canonical middleware image | exact checksums and image digest | private authenticated adapter only |

The existing signed middleware digest
`sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff`
is authorized for isolated staging only. It is not a production artifact and
must not be entered as the production digest.

Production deployment requires a generated manifest in which every placeholder
below is replaced by an exact protected merge SHA, digest or checksum. The
release gate must reject feature-branch SHAs, mutable image tags, a staging-only
approval, absent signatures, or any mismatch found by runtime readback.

## Change ownership

| Change | Owning repository | Reason | Required runtime artifact | Coverage |
| --- | --- | --- | --- | --- |
| Stream/consumer topology, retries, retention and replay policy | production-platform | infrastructure contract | signed configuration bundle | isolated real-NATS contract tests |
| Keycloak production/staging contract and PostgreSQL role policy | production-platform | deployment security policy | signed configuration bundle | authorization and isolated PostgreSQL tests |
| Event envelope validation and tenant/campaign subjects | canonical middleware | executable application behavior | middleware image | transport contract tests |
| Stable message-ID publication | canonical middleware | executable NATS client behavior | middleware image | publisher unit tests |
| Maximum-delivery advisory subscription and DLQ forwarding | both | platform provisions policy; middleware executes it | configuration bundle plus middleware image | real-NATS runtime and middleware worker tests |
| Odoo/n8n/callback effective-once implementation | canonical middleware | business integration behavior | middleware image | canonical integration suite |

Production flags remain false throughout candidate construction and staging.
