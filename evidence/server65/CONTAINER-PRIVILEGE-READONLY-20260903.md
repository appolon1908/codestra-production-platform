# Container privilege read-only audit

Date: 2026-09-03
Target: `65.109.65.169`
Access: existing `codestra-app` operator; Docker inspect only.

| Property | Count |
|---|---:|
| Running containers | 106 |
| `Privileged=true` | 0 |
| User root or empty (effective default) | 31 |
| Read-only root filesystem | 0 |
| Containers with `CapAdd` | 12 |

No privileged container was observed. However, the absence of read-only root
filesystems and the 31 root/empty-user containers prevent a complete hardened
container certification. The 12 capability additions require service-by-
service justification before SECURITY can pass.

SECURITY=FAIL
DOCKER_SOCKET_PROTECTED=UNVERIFIED
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
