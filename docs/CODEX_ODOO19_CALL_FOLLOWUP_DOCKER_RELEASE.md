# Codex Directive — Odoo 19 Call Follow-up Docker Release

## Repository and candidate

```text
repository: appolon1908-hue/codestra-production-platform
packaging branch: ops/odoo19-call-followup-docker-release
source integration branch: integration/odoo19-call-followup-release-candidate-20260826
source integration SHA: 32ef97f27459cf57c58e7b329ab8ed0ae9c0f34d
core source SHA: 3bf43b689da96eb1ab2444c30133a2dc43563be4
API source SHA: 985869b17ebd3211b87c48cf620bb34a011b910b
UX source SHA: 0c8568f36e0fd1c8e508145801d4abf32e0d85f0
automation source SHA: dd468a79376ef595df13cfe9e142204a7771b5eb
```

This packaging branch is a staging candidate, not production authority.
Production requires the source PRs to merge normally into the protected
release branch, the Docker branch to be rebased onto that exact merged
lineage, and fresh approval and evidence on the unchanged final SHA.

## Read first

Read completely before editing or running deployment:

1. `AGENTS.md`
2. `CODEX_APP_SERVER_A.md`
3. PR #114 and all unresolved review threads
4. API PR #126
5. UX PR #128
6. automation PR #131
7. `deploy/odoo/call-followup-release/README.md`
8. `deploy/odoo/call-followup-release/ROLLBACK.md`
9. each addon README and test suite
10. current Odoo production and staging Compose files

Preserve unrelated work. Never commit credentials, production customer
data, recordings, mail bodies, database dumps, or filestore content.

## Non-negotiable architecture

- Odoo and n8n never write directly to VICIdial, PBX tables, DIDWW, Twilio,
  or another carrier.
- Codestra middleware remains the authoritative telephony gateway.
- Completed-call ingestion uses an authenticated non-human Odoo API-key
  identity.
- Remote automation delivery defaults to disabled.
- The automation addon may send only to the approved middleware endpoint.
- A failed migration leaves Odoo stopped until rollback or a reviewed repair.
- Never deploy a moving branch or tag. Build and deploy exact SHAs and image
  digests.
- Never treat a Docker image rollback as a database schema rollback.

## Branch and merge order

Keep each heavy feature independently reviewable:

1. merge core PR #114 through protected review;
2. retarget/rebase API PR #126 to the protected release branch, rerun checks,
   obtain fresh exact-SHA approval, and merge;
3. retarget/rebase UX PR #128, rerun checks, obtain approval, and merge;
4. retarget/rebase automation PR #131, rerun checks, obtain approval, and
   merge;
5. rebuild the integration candidate from the resulting protected branch;
6. rebase the Docker packaging branch onto that exact lineage;
7. rerun every validation and obtain independent approval of the final
   packaging SHA.

Do not squash unrelated branches into one unreviewable production commit.

## Phase 1 — source review

From a clean worktree:

```bash
git status --short
git branch --show-current
git rev-parse HEAD

python scripts/validate_odoo_crm_call_followup.py
python scripts/validate_odoo_crm_call_followup_api.py
python scripts/validate_odoo_crm_call_followup_ux.py
python scripts/validate_odoo_crm_call_followup_automation.py
python scripts/validate_odoo_call_followup_docker_release.py

deploy/odoo/call-followup-release/validate.sh
```

Review all Python, XML, JavaScript, SCSS, ACLs, record rules, cron records,
schemas, shell scripts, Compose files, and Docker build instructions. Fix
defects only on the branch that owns the affected feature.

## Phase 2 — immutable image build

Verify the Dockerfile base image is digest pinned. The build must use the
exact clean Git HEAD as `VCS_REF`.

Local non-release build:

```bash
PUSH=false deploy/odoo/call-followup-release/build.sh
```

Registry release build:

```bash
docker login ghcr.io

PUSH=true \
  IMAGE_REPOSITORY=ghcr.io/appolon1908-hue/codestra-odoo-call-followup \
  deploy/odoo/call-followup-release/build.sh
```

Release requirements:

- no `latest` tag;
- pushed image includes max-mode provenance and an SBOM;
- capture the emitted `repository@sha256` reference;
- inspect OCI labels and `/opt/codestra/release/call-followup-manifest.json`;
- verify all four addon directories exist in `/opt/codestra/addons`;
- scan the image using the repository's approved scanner;
- sign the digest through the existing protected signing workflow when
  available;
- record builder, timestamp, source SHA, image digest, SBOM, provenance,
  scan result, and signature evidence.

## Phase 3 — disposable Odoo 19 test

Use an isolated PostgreSQL database and matching temporary filestore. Do not
point the disposable test at production volumes or networks.

Run a clean install of all four modules with tests:

```text
codestra_crm_call_followup
codestra_crm_call_followup_api
codestra_crm_call_followup_ux
codestra_crm_call_followup_automation
```

Acceptance:

- Odoo registry loads;
- every view compiles;
- backend assets compile;
- ACL and record rules load;
- cron records load;
- mail templates and calendar alarms load;
- addon tests pass;
- module upgrade passes;
- automation remains disabled;
- image healthcheck passes;
- no external request occurs.

Preserve sanitized logs and destroy the disposable database and filestore.

## Phase 4 — staging Docker deployment

Inventory staging first. Record:

- exact staging Compose files and project name;
- current app SHA and image digest;
- Odoo version;
- PostgreSQL version;
- database and filestore location;
- web, worker, cron, bus, and mail topology;
- middleware endpoint and feature-flag state;
- available disk space;
- rollback owner.

Create and verify a PostgreSQL backup and matching filestore backup before
module installation or upgrade.

Set a colon-separated staging Compose base:

```bash
export BASE_COMPOSE_FILES="<staging-base.yaml>:<staging-override.yaml>"
export ODOO_CALL_FOLLOWUP_IMAGE="<repository>@sha256:<digest>"
export ODOO_CALL_FOLLOWUP_RELEASE_SHA="<exact-packaging-sha>"
export APPROVED_HEAD_SHA="$ODOO_CALL_FOLLOWUP_RELEASE_SHA"
export ODOO_DATABASE="<staging-database>"
export MODULE_OPERATION=install
export DATABASE_BACKUP_ID="<verified-staging-db-backup>"
export FILESTORE_BACKUP_ID="<verified-staging-filestore-backup>"
export INCLUDE_AUTOMATION_SECRETS=NO

deploy/odoo/call-followup-release/deploy.sh staging
```

Use `MODULE_OPERATION=upgrade` only when all four modules are already
installed at a prior reviewed version.

### Optional automation secret mounting

Mount only synthetic staging credentials first:

```bash
export INCLUDE_AUTOMATION_SECRETS=YES
export ODOO_CALL_FOLLOWUP_AUTOMATION_API_KEY_FILE="<root-owned-host-file>"
export ODOO_CALL_FOLLOWUP_AUTOMATION_WEBHOOK_SECRET_FILE="<root-owned-host-file>"
```

Configure these Odoo parameters through an audited Odoo shell or approved
configuration process:

```text
codestra.call_followup_automation.target_url=https://<approved-middleware>/...
codestra.call_followup_automation.tenant_id=<staging-tenant>
codestra.call_followup_automation.api_key_file=/run/secrets/codestra_call_followup_automation_api_key
codestra.call_followup_automation.webhook_secret_file=/run/secrets/codestra_call_followup_automation_webhook_secret
codestra.call_followup_automation.timeout_seconds=5
codestra.call_followup_automation.enabled=False
```

Secret mounting does not authorize remote delivery.

## Phase 5 — staging acceptance

Use synthetic CRM contacts and test mailboxes only.

### Core popup and forms

- send an authorized completed-call event through middleware;
- verify only the assigned agent receives the popup;
- verify outcome, notes, schedule, and email tabs render;
- verify Save & Complete;
- verify Send Email & Complete;
- verify Schedule & Complete;
- verify Complete Without Email;
- verify Open CRM and Open Customer;
- verify required fields and invalid email messages;
- verify callback and appointment calendar creation;
- verify reschedule and cancellation synchronization;
- verify 30-minute in-app reminder;
- verify separate 15-minute client and agent emails;
- verify the immediate email remains queued and retryable;
- verify the layout at desktop and narrow/mobile widths.

### UX recovery

- snooze for 5, 15, and 30 minutes;
- verify future snoozes are absent from pending startup actions;
- verify the cron releases each due item once;
- close an unfinished modal and confirm it returns without two active dialogs;
- disconnect/reconnect the browser and verify pending recovery;
- verify another agent cannot read, snooze, or complete the item.

### API v1

- authenticate using the service API key;
- validate a payload without creating a record;
- register a valid event;
- replay the same event and confirm one record with `replayed=true`;
- retry with a different correlation ID;
- replay with changed immutable data and confirm rejection;
- reject unknown fields;
- reject cross-company and mismatched agent/customer references;
- reconcile status after a simulated client timeout.

### Durable automation

With delivery disabled:

- completing a call creates immutable outbox rows in the same database
  transaction;
- no remote request occurs;
- duplicate completion creates no duplicate event;
- payloads contain no notes, email bodies, recipient addresses, recordings,
  or credentials;
- managers can inspect but not directly edit or delete events.

Then, only against an approved synthetic middleware endpoint, enable staging
delivery and verify:

- HMAC and timestamp validation;
- API-key authentication;
- idempotency and correlation propagation;
- two workers cannot claim the same row;
- timeout and 5xx retry;
- 408 and 429 retry;
- permanent 4xx dead-letter;
- bounded retry exhaustion;
- Retry Now and Move to Dead Letter;
- middleware read-back and n8n routing remain inactive unless separately
  approved.

Disable remote delivery again after acceptance.

### Runtime and observability

- web health;
- Odoo workers and cron;
- bus/websocket delivery;
- PostgreSQL locks and connections;
- mail queue;
- container restarts;
- CPU and memory;
- outbox pending/retry/dead counts;
- logs contain no credentials or unrestricted PII.

Rehearse the complete rollback using the staging database and filestore.

## Production GO/NO-GO

Production is `NO_GO` unless every value is true:

```text
CORE_PR_MERGED=YES
API_PR_MERGED=YES
UX_PR_MERGED=YES
AUTOMATION_PR_MERGED=YES
DOCKER_PR_MERGED=YES
EXACT_FINAL_SHA_APPROVED=YES
REQUIRED_CHECKS=PASS
IMAGE_DIGEST_RECORDED=YES
SBOM=PASS
PROVENANCE=PASS
IMAGE_SCAN=PASS
DISPOSABLE_INSTALL=PASS
STAGING_INSTALL_OR_UPGRADE=PASS
ODOO_TESTS=PASS
API_ACCEPTANCE=PASS
POPUP_AND_CTA_ACCEPTANCE=PASS
REMINDER_EMAIL_ACCEPTANCE=PASS
OUTBOX_ACCEPTANCE=PASS
MULTI_COMPANY_ISOLATION=PASS
DATABASE_BACKUP=VERIFIED
FILESTORE_BACKUP=VERIFIED
ROLLBACK_REHEARSAL=PASS
MONITORING_AND_ALERTS=PASS
CHANGE_WINDOW=APPROVED
```

## Production deployment

Set all required gates explicitly:

```bash
export BASE_COMPOSE_FILES=deploy/odoo/compose.production.yaml
export ODOO_CALL_FOLLOWUP_IMAGE="<repository>@sha256:<digest>"
export ODOO_CALL_FOLLOWUP_RELEASE_SHA="<exact-approved-packaging-sha>"
export APPROVED_HEAD_SHA="$ODOO_CALL_FOLLOWUP_RELEASE_SHA"
export ODOO_DATABASE="<production-database>"
export MODULE_OPERATION=install
export DATABASE_BACKUP_ID="<verified-production-db-backup>"
export FILESTORE_BACKUP_ID="<verified-production-filestore-backup>"
export REQUIRED_CHECKS=PASS
export INDEPENDENT_REVIEW=APPROVED
export STAGING_ACCEPTANCE=PASS
export ROLLBACK_REHEARSAL=PASS
export CHANGE_ID="<approved-change-id>"
export ROLLBACK_IMAGE="<previous-repository>@sha256:<digest>"
export ROLLBACK_APP_SHA="<previous-application-sha>"
export ALLOW_PRODUCTION_DEPLOY=YES
export PRODUCTION_CONFIRMATION="DEPLOY $APPROVED_HEAD_SHA"
export INCLUDE_AUTOMATION_SECRETS=NO

deploy/odoo/call-followup-release/deploy.sh production
```

The script pulls the exact digest, stops Odoo, runs a one-shot install or
upgrade, starts Odoo, checks health, and writes evidence. It does not declare
production complete.

## Canary

Keep remote automation delivery disabled. Assign the feature to one approved
canary agent. Use a synthetic completed-call event; do not place a live call
solely to test deployment.

Verify popup, all CTAs, CRM/customer links, email queue, callback calendar,
bus recovery, snooze, reminders, ACLs, and audit. Monitor logs, health,
PostgreSQL, mail queue, and container resources. Expand access only after
signed canary acceptance.

Remote automation activation is a separate change requiring middleware HMAC,
retry, dead-letter, monitoring, and rollback evidence.

## Rollback

Follow `deploy/odoo/call-followup-release/ROLLBACK.md`. When module schema or
persistent data changed, restore the matching PostgreSQL and filestore
backups before starting the previous image. Retain middleware events for
replay and reconcile before re-enabling delivery.

## Final Codex report

Return:

1. current directory;
2. repository and branch;
3. starting and final SHAs;
4. commits created;
5. source PR states and merge SHAs;
6. image tag and immutable digest;
7. SBOM, provenance, scan, and signature evidence;
8. Compose files used;
9. database and filestore backup IDs;
10. install/upgrade command and result;
11. module versions and states;
12. Odoo test results;
13. API acceptance results;
14. popup/form/CTA results;
15. calendar and reminder results;
16. mail queue results;
17. UX snooze/reconnect results;
18. outbox/retry/dead-letter results;
19. multi-company and authorization results;
20. container health and monitoring results;
21. rollback rehearsal and exact rollback procedure;
22. unresolved blockers;
23. `MERGED=YES|NO`;
24. `PRODUCTION_DEPLOYED=YES|NO`;
25. `AUTOMATION_REMOTE_DELIVERY_ENABLED=YES|NO`.

Do not claim a pass without command output and runtime evidence.
