# Codestra CRM Call Follow-up Realtime Leases

Optional Odoo 19 extension for coordinating automatic post-call popups across multiple tabs, browser windows, workers, and reconnects.

## Behavior

- one browser tab atomically claims one pending post-call action;
- PostgreSQL `FOR UPDATE SKIP LOCKED` prevents concurrent claims;
- each claim receives an opaque random lease token;
- the owning tab renews the lease while its modal is open;
- closing the modal releases the lease;
- completion, cancellation, and snooze clear it automatically;
- abandoned leases expire after 120 seconds and become reclaimable;
- only the assigned agent in an active company may claim, renew, or release;
- the extension replaces the core popup browser service, but does not alter email, calendar, analytics, telephony, or Docker behavior.

## RPC methods

Model:

```text
codestra.crm.call.followup
```

Methods:

```text
claim_pending_post_call_actions(client_instance_id, limit=5)
renew_popup_lease(ids, client_instance_id, lease_token)
release_popup_lease(ids, client_instance_id, lease_token)
```

Lease tokens are browser coordination credentials. Do not log or persist them outside the Odoo record and current browser session.

## Installation

Install only after the independently reviewed core addon:

```bash
./odoo-bin \
  -d <database> \
  --addons-path=<repo>/odoo_addons,<odoo-core>/addons \
  -i codestra_crm_call_followup_realtime \
  --stop-after-init
```

## Required evidence

- two tabs race for the same pending call and only one receives it;
- second tab can claim after release;
- stale lease is reclaimed after expiry;
- active lease renews without rotating the token;
- another agent and company are denied;
- completion, cancellation, and snooze clear lease state;
- browser reload and worker restart recover unfinished actions;
- no duplicate calendar event, email, or chatter entry occurs.
