# Kong source authority

Kong implementation and database operations are owned by
`appolon1908-hue/Kong` at the immutable commit recorded in
`config/kong-source.lock.json`.

The platform repository retains only the cross-system dependency contract,
release lock, and verification tooling. It no longer owns Kong route manifests,
plugin configuration, standby implementation, database roles, backup/PITR/HA
scripts, or Kong-specific tests.

This source move does not change the production topology:

```text
public client -> host Caddy -> Docker upstream-gateway -> private Kong -> private services
```

Updating the lock requires a reviewed Kong commit, passing standalone Kong CI,
an updated platform PR, and exact-head validation. Applying a Kong change to the
live Admin API remains a separate maintenance-window operation.
