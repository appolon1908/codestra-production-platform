# Production monitoring deployment

This procedure prepares deployment; it does not authorize activation.

## Preconditions

All 20 governance fields in `/etc/codestra/governance/production.env` must contain approved references, including protected primary/secondary owners, escalation timing, escalation policy, monitoring approval, and change/rollback ownership. The primary, secondary, recovery, and rejected-route audit receiver URL files must be nonempty, protected with mode 0400/0440/0600/0640, and contain approved non-placeholder HTTP(S) URLs. `.invalid`, example, localhost, inline, empty, and placeholder receiver values are rejected.

Keep `SEND_EVENTS=false`, `PRODUCTION_CALLBACKS_ENABLED=false`, `VICIDIAL_WRITES_ENABLED=false`, `EXTERNAL_DIAL_ENABLED=false`, `TRANSFERS_ENABLED=false`, `N8N_PRODUCTION_WORKFLOWS_ENABLED=false`, and `WEBRTC_PRODUCTION_ROUTES_ENABLED=false`. The sync service must remain disabled and inactive. Do not mutate or deliver the 1,110 quarantined historical events.

## Validate without starting

```sh
sudo env CODESTRA_MONITORING_VALIDATE_ONLY=true \
  CODESTRA_ALERTMANAGER_CONFIG=/etc/codestra/monitoring/alertmanager.yml \
  CODESTRA_GOVERNANCE_REFERENCES=/etc/codestra/governance/production.env \
  /opt/codestra/operations/monitoring/install-monitoring.sh
```

Record config digests and parser output. Validation is not deployment approval.

## Approved deployment only

After external receiver, owner, escalation, approval, and window gates pass, the authorized change owner may run the installer without validate-only. The Compose project uses durable named volumes for Prometheus and Alertmanager. Never substitute test receivers or placeholder URLs. Do not expose monitoring endpoints outside the approved administration network.

## Verification

Confirm container health, rule count, durable volumes, environment routing, primary/secondary/recovery slots, and redacted logs. A separate approved production delivery exercise is required; Phase 5A does not perform it.

## Stop conditions

Stop before deployment when any governance value, receiver file, escalation interval, owner record, approval, protected permission, safety flag, or rollback owner is absent or invalid.
