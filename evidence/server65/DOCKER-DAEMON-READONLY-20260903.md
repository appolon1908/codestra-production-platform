# Docker daemon read-only security read-back

Date: 2026-09-03
Target: `65.109.65.169`
Access: approved `codestra-app` operator; `docker info` only.

- Docker Server Version: `29.7.2`
- Storage driver: `overlayfs`
- Logging driver: `json-file`
- Cgroup driver: `systemd`
- Security options: `apparmor`, `seccomp`
- Host OS: Ubuntu `22.04.5 LTS`
- Kernel: `5.15.0-190-generic`
- Live restore: `false`

The daemon exposes AppArmor and seccomp, but live-restore is disabled and the
logging driver remains local JSON files. This is informational evidence only;
retention, log shipping, daemon configuration provenance, and restart impact
are not certified.

DOCKER_DAEMON_SECURITY=PARTIAL
SECURITY=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
