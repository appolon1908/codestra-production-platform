# Docker socket and host-network read-only audit

Date: 2026-09-03
Target: `65.109.65.169`
Access: existing `codestra-app` operator; Docker inspect only.

- Running containers inspected: `106`
- Containers mounting a Docker socket: `0`
- Containers using host network mode: `0`
- Privileged containers: `0`

This proves the inspected container set does not expose `/var/run/docker.sock`,
use host networking, or run privileged. It does not certify per-service Linux
capabilities, filesystem ownership, or runtime observability controls.

DOCKER_SOCKET_PROTECTED=PASS
HOST_NETWORK_ISOLATION=PASS
SECURITY=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
