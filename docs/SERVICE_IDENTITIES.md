# Service Identities and SSH

| Alias / identity | Target | Key mode | Live result | Required action |
|---|---|---|---|---|
| `codestra-vicidial` / `codestra-admin` | `65.21.67.207` | 0600 | PASS: identity, hostname, addresses | none |
| `kyqra-server` / `kyqra-deploy` | `10.40.0.2` | 0600 | BLOCKED: account absent/key rejected | peer owner creates least-privilege account and installs existing public key |
| `telnexa-server` / `telnexa-deploy` | `10.40.0.2` | 0600 | BLOCKED: account absent/key rejected | same |
| `klyrow-server` / `klyrow-deploy` | `10.40.0.2` | 0600 | BLOCKED: account absent/key rejected | same |

The stale private-IP host key was repaired only after its ED25519 fingerprint exactly matched the independently pinned public endpoint. Backup: `/root/.ssh/known_hosts.before-connectivity-audit-20260815.bak`. SSH policy was not weakened.
