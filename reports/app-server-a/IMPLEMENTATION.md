# Application Server A Implementation

Verified UTC: 2026-07-27.

## Campaign design slice

Implemented `campaign_provisioning`, a dependency-free desired-state component
that cannot call Odoo, n8n, VICIdial, or the peer adapter.

The component now:

- validates immutable integration UUIDs, business-unit ownership, canonical
  identifier parts, direction, environment, required policies, roles, owner,
  and supervisor;
- creates the canonical campaign, list, group, script, disposition, n8n scope,
  policy, reporting, test-plan, and rollback fields;
- holds VICIdial resources, n8n workflows, provisioning, lead publication,
  agent synchronization, live call control, and production dialing disabled;
- persists immutable revision 1 and its canonical manifest hash;
- returns the existing manifest for an identical replay;
- rejects an integration UUID replay with changed desired state;
- allocates production IDs from the correct business-unit range and all
  non-production IDs from 91000-91999;
- uses `BEGIN IMMEDIATE` plus unique constraints rather than `MAX()+1`.

## Verification

`pytest -q` passes 94 tests and 9 subtests. New coverage includes complete
disabled preview generation, replay idempotency, changed-payload conflict,
invalid scope/policy rejection, staging range isolation, and 24 concurrent
allocations without duplicates.

`python3 -m compileall -q campaign_provisioning` and `git diff --check` pass.

## Safety

This slice performs local desired-state persistence only. It did not contact a
mutation endpoint, change a firewall rule, expose a database, activate an n8n
workflow, or enable a production feature flag.

## Next integration boundary

Connect the design service to an authenticated middleware preview endpoint and
the Odoo transactional outbox consumer. Approval and adapter provisioning must
remain separate operations and must retain read-back and activation gates.
