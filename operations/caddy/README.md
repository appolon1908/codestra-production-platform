# Caddy production edge authority

This directory is the non-secret authority for host Caddy. `live/` maps to `/etc/caddy`; `systemd/` maps to the Caddy unit and drop-ins; `logging/` maps to logrotate. Runtime PKI, ACME state, htpasswd files, client credentials, and all private keys are protected state and are never stored in Git.

Traffic remains: Internet → host Caddy → internal upstream-gateway Caddy → Kong → services. The documented realtime exceptions remain direct to the approved WebSocket gateway.

## Operations

Run `scripts/validate.sh` before deployment. `scripts/audit-endpoints.sh` verifies every adapted upstream TCP endpoint, Kong hostname coverage, and public bypass closure. `scripts/diff-live.sh` reports active unexpected drift. `scripts/deploy.sh` installs only after validation and creates an atomic rollback snapshot. `scripts/rollback.sh` restores such a snapshot and verifies Caddy before reload. `scripts/backup-state.sh` creates a GPG-encrypted state archive and sends it to the approved backup host. `scripts/restore-state.sh` restores only into an isolated directory unless explicitly extended by an operator.

Monitoring is generated into the node-exporter textfile collector by `scripts/monitor.sh`; alert rules are in `monitoring/caddy-production.rules.yml`. Private mTLS material is referenced by path and read only at probe time.

See `OWNERSHIP.tsv`, `HOST-OWNERSHIP.tsv`, and `CADDY-KONG-CONTRACT.md` for reconstruction and boundary ownership.
