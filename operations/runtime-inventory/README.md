# Read-only runtime inventory authority

This package gives a certification identity access to one root-owned evidence
command without Docker-group membership or general sudo. The command accepts no
arguments and emits only the fixed `codestra.runtime-inventory.v1` JSON schema.

It reports container name, configured image, runtime image ID, immutable-reference
status, health, restart count, networks, published ports, allowlisted OCI release
labels, and normalized allowlisted safety flags. It never emits arbitrary labels,
environment variables, mounts, commands, logs, filesystem content, or secret values.

Installation is a separately reviewed infrastructure change:

```text
install-runtime-inventory.sh
usermod -aG codestra-runtime-audit <certification-identity>
```

The identity must start a new login session before running:

```text
sudo -n /usr/local/sbin/codestra-runtime-inventory
```

Do not add the identity to `docker`, weaken `/var/run/docker.sock`, or broaden the
sudoers entry. Removing the identity from `codestra-runtime-audit` revokes access.
