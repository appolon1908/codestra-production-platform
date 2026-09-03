# Docker network read-only audit

Date: 2026-09-03
Target: `65.109.65.169`
Access: approved `codestra-app` operator; `docker network inspect` only.

- Networks: `52`
- Internal-only networks: `34`
- Non-internal networks: `18`
- Bridge networks: `50`
- Networks with `staging` in the name: `15`
- Networks with test/CI/clone/remediation/rehearsal indicators: `7`

The database and queue services observed earlier remain loopback-published,
but the host contains substantial staging and test network residue. Network
ownership, lifecycle, egress policy, and production/staging separation are not
fully certified.

NETWORK_EXPOSURE=PARTIAL
STAGING_ISOLATED=FAIL
SECURITY=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
