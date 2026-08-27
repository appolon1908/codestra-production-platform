# Runtime Integration Fabric Branch Map

Parent architecture branch: `architecture/caddy-kong-runtime-fabric-v2`

- `platform/caddy-edge-v2`
- `platform/kong-core-cell-v2`
- `platform/kong-beyvra-cell-v2`
- `platform/kong-telephony-cell-v2`
- `platform/n8n-core-cell-v2`
- `platform/n8n-beyvra-cell-v2`
- `platform/n8n-telephony-cell-v2`
- `observability/integration-fabric-v2`
- `testing/integration-fabric-no-effect-v2`
- `release/integration-fabric-v2`

Do not combine Caddy, Kong, n8n, observability, staging, or release changes. Every branch receives a separate PR, exact-head review, and rollback plan.
