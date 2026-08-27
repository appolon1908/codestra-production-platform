# Integration Fabric Deployment Boundary

This directory is a placeholder for future reviewed runtime overlays. No Compose or Caddy apply file is committed by the architecture branch.

Future implementation must use separate branches:

- `platform/caddy-edge-v2`
- `platform/kong-core-cell-v2`
- `platform/kong-beyvra-cell-v2`
- `platform/kong-telephony-cell-v2`
- `platform/n8n-core-cell-v2`
- `platform/n8n-beyvra-cell-v2`
- `platform/n8n-telephony-cell-v2`
- `observability/integration-fabric-v2`

Every overlay must render in CI, bind exact immutable digests, use external secrets and durable volumes, expose no administration listener publicly, preserve all capabilities false, and pass backup/restore and rollback before staging apply.
