# Five-component source release status

This document records public repository and GitHub Actions information for the requested Kong, Caddy, Odoo, Middleware, and n8n release preparation. It contains no host inventory, network topology, runtime configuration, credentials, or operational evidence.

## Source snapshot

Observed on 2026-09-09. Branches can advance after this observation; deployment must recheck its selected commit.

| Repository | Observed main commit | Public source-check observation |
| --- | --- | --- |
| [Kong](https://github.com/appolon1908-hue/Kong) | `d1e7e77e2566a72c4a75668807e72b233ccba06b` | Source/configuration and certification jobs passed. |
| [Caddy](https://github.com/appolon1908-hue/Caddy) | `dc6f7e4447d76d611d9b8ce9068b34e87b90d948` | Source validation and immutable-candidate jobs passed; a separate administration job failed. |
| [Odoo](https://github.com/appolon1908-hue/Odoo) | `1d645640bee8f611b395490d2cd90fc5316af5bc` | Source validation, merged-runtime test, and image build/scan passed. |
| [Middleware-](https://github.com/appolon1908-hue/Middleware-) | `5e252a4afb668dda87806f638c922e3b9d6c8767` | CI and signed-image verification passed; the promotion workflow is waiting. |
| [N8N](https://github.com/appolon1908-hue/N8N) | `72be40d4e738a22d5531e14578edddcab7a4803a` | Exact-source validation and immutable-candidate jobs passed. |

## Public workflow references

- Kong validation: https://github.com/appolon1908-hue/Kong/actions/runs/34370470715
- Kong certification: https://github.com/appolon1908-hue/Kong/actions/runs/34370470674
- Caddy validation: https://github.com/appolon1908-hue/Caddy/actions/runs/33885142205
- Caddy readiness: https://github.com/appolon1908-hue/Caddy/actions/runs/33885142903
- Caddy administration job: https://github.com/appolon1908-hue/Caddy/actions/runs/34306189553
- Odoo source/runtime validation: https://github.com/appolon1908-hue/Odoo/actions/runs/34396010050
- Odoo image build/scan: https://github.com/appolon1908-hue/Odoo/actions/runs/34396010087
- Middleware CI: https://github.com/appolon1908-hue/Middleware-/actions/runs/34404823250
- Middleware signed release: https://github.com/appolon1908-hue/Middleware-/actions/runs/34405126212
- Middleware promotion gate: https://github.com/appolon1908-hue/Middleware-/actions/runs/34405398045
- n8n source validation: https://github.com/appolon1908-hue/N8N/actions/runs/34371889382
- n8n readiness: https://github.com/appolon1908-hue/N8N/actions/runs/34371889830

## Interpretation

Source CI and image verification do not establish a completed deployment. Skipped staging and canary jobs are not runtime certification.

At the observed Middleware commit, `.github/workflows/automated-production-promotion.yml` verifies the release and records read-only admission in a job summary. Its admission job does not execute a deployment controller or replace running services. A passing admission job therefore must not be described as a completed server deployment.

This is a documentation-only change. It does not change release locks, authorize a candidate, alter repository protections, or deploy any component.
