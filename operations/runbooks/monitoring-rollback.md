# Production monitoring rollback

## Trigger

Rollback for invalid configuration, route leakage, restart loop, receiver flooding, secret exposure risk, false successful-delivery recording, excessive resource use, or an approved rollback decision.

## Procedure

1. Preserve redacted Prometheus and Alertmanager logs, current config/rule/template digests, alert fingerprints, volume identity, and UTC timestamps.
2. Stop only the `codestra-monitoring` Compose project. Do not stop application services and do not alter any call, workflow, write, callback, transfer, WebRTC, or queue safety flag.
3. Restore the last approved non-secret configuration by recorded commit/digest.
4. Run `promtool`, `amtool`, the Phase 5A validator, environment-routing tests, and Compose rendering before any approved restart.
5. Preserve durable volumes unless the recovery owner explicitly authorizes data disposal. Never delete alert evidence as a rollback shortcut.
6. If receiver or owner data is uncertain, leave monitoring undeployed and all external gates blocked.

No rollback step may deliver or mutate the 1,110 quarantined historical events, activate calls, or weaken DNC fail-closed behavior. A restart requires the same external approval and protected receiver prerequisites as initial deployment.
