# Synthetic automatic-campaign gate — blocked safely

Date: 2026-07-27

## Result

`BLOCKED_SAFE`

The approved private mTLS listener resolved to `10.40.0.2:8443` and accepted
the pinned client certificate. The authoritative readiness response was:

```json
{
  "status": "not_ready",
  "components": {
    "database": "staging-only",
    "spool": "available",
    "agent_adapter": "disabled",
    "non_agent_adapter": "disabled",
    "event_publisher": "disabled",
    "clock": "not_checked"
  }
}
```

The approved campaign reporting route returned HTTP 503. The restricted
campaign-status route returned HTTP 403 for the currently installed client
identity. No direct MariaDB connection was attempted.

## Safety state

- Production dialing remained disabled.
- External delivery and customer communication remained disabled.
- No telephone number was supplied.
- No lead, campaign, list, group, script, disposition, workflow, or endpoint
  was created or activated during this blocked attempt.
- Existing disabled staging fixture state was preserved.
- No public listener or firewall exception was added.

## Required continuation

Enable the approved Server B `non_agent_adapter` and its campaign read-back
route for the pinned middleware mTLS identity, while retaining private-only
binding and fail-closed write flags. Then rerun
`scripts/synthetic_automatic_campaign_gate.py` before executing the lifecycle.
