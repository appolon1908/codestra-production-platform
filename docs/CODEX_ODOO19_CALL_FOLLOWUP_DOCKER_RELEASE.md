# Codex Directive — Odoo 19 Call Follow-up Docker Release

## 1. Exact scope

Work in this repository and preserve the branch boundaries below:

```text
repository: appolon1908-hue/codestra-production-platform
core PR: #114
API PR: #126
UX PR: #128
automation PR: #131
Docker PR: #135

core branch: feature/odoo19-crm-call-followup-final-20260826
core SHA: 3bf43b689da96eb1ab2444c30133a2dc43563be4

API branch: feature/odoo19-call-followup-api-contract-v1
API SHA: 985869b17ebd3211b87c48cf620bb34a011b910b

UX branch: feature/odoo19-call-followup-ux-actions
UX SHA: 3bcca91f62a8e1ca67c9e4b850a72a9f317ed431

automation branch: feature/odoo19-call-followup-automation-outbox
automation SHA: fde96222979e43f213f49eeee3d695bfdc862ddb

integration branch: integration/odoo19-call-followup-release-candidate-20260826
integration SHA: b9b55274d726b2375f0a48ae30a2b1369c47e91c

Docker branch: ops/odoo19-call-followup-docker-release
```

The Docker branch is a staging release candidate. It is not production
authority. Do not merge it into the protected release branch or deploy it to
production until all source PRs have passed protected review, have been merged
in order, and this package has been rebuilt on that exact merged lineage.

## 2. Required reading

Read these files completely before editing or deploying:

1. `AGENTS.md`
2. `CODEX_APP_SERVER_A.md`
3. all open review threads in PRs #114, #126, #128, #131, and #135
4. each call-follow-up addon README and test suite
5. `deploy/odoo/call-followup-release/README.md`
6. `deploy/odoo/call-followup-release/ROLLBACK.md`
7. the production and staging Compose files actually used on the server
8. the current Odoo, PostgreSQL, filestore, bus, cron, mail, backup, and
   monitoring configuration

Preserve unrelated work. Never commit credentials, access tokens, mail bodies,
recordings, customer data, database dumps, filestore data, or server-specific
secret paths.

## 3. Non-negotiable architecture

- Odoo and n8n never write directly to VICIdial tables, PBX tables, DIDWW,
  Twilio, or another carrier.
- Codestra middleware remains the authoritative telephony gateway.
- Completed-call ingestion uses an authenticated non-human Odoo API-key
  identity with the minimum company and group access.
- The API boundary remains versioned, strict, idempotent, and reconcilable.
- Agent notes, email bodies, recipient addresses, recordings, credentials, and
  raw provider payloads never enter the automation outbox.
- Automation may deliver only to the exact approved middleware hostname.
- Redirect responses are rejected.
- Remote automation delivery remains disabled until a separate staging and
  production activation change is approved.
- A failed module installation or upgrade leaves Odoo stopped until rollback or
  an independently reviewed repair is completed.
- Build and deploy exact Git SHAs and exact image digests. Never deploy a moving
  branch, a mutable tag, or `latest`.
- A Docker image rollback is not a database rollback. When module schema or
  persistent data changed, restore the matching PostgreSQL backup and filestore
  together.

## 4. Branch ownership and merge order

Fix defects on the branch that owns the affected behavior:

- core forms, CRM/calendar/email behavior: core branch and PR #114;
- completed-call RPC contract and middleware client: API branch and PR #126;
- snooze, popup recovery, responsive layout, and user CTAs: UX branch and PR
  #128;
- durable outbox, retry, dead letter, HMAC, host policy, and worker leasing:
  automation branch and PR #131;
- image construction, Compose, deployment gates, evidence, and rollback:
  Docker branch and PR #135.

Required protected merge order:

1. merge core PR #114;
2. retarget/rebase API PR #126 to the protected release branch, rerun checks,
   obtain fresh approval for the exact head, and merge;
3. retarget/rebase UX PR #128, rerun checks, obtain fresh approval, and merge;
4. retarget/rebase automation PR #131, rerun checks, obtain fresh approval, and
   merge;
5. recreate the integration candidate from the exact protected lineage;
6. rebase or rebuild the Docker branch on that integration SHA;
7. update every embedded source SHA and manifest;
8. rerun all source, Docker, security, image, and runtime gates;
9. obtain independent approval applying to the unchanged final Docker head.

Do not collapse unrelated source branches into one unreviewable production
commit.

## 5. Source validation

From a clean Docker-branch worktree:

```bash
git status --short
git branch --show-current
git rev-parse HEAD

git diff --check
python -m compileall -q \
  odoo_addons/codestra_crm_call_followup \
  odoo_addons/codestra_crm_call_followup_api \
  odoo_addons/codestra_crm_call_followup_ux \
  odoo_addons/codestra_crm_call_followup_automation \
  integrations/odoo_call_followup_client.py \
  scripts

python scripts/validate_odoo_crm_call_followup.py
python scripts/validate_odoo_crm_call_followup_api.py
python scripts/validate_odoo_crm_call_followup_ux.py
python scripts/validate_odoo_crm_call_followup_automation.py
python scripts/validate_odoo_call_followup_docker_release.py

deploy/odoo/call-followup-release/validate.sh
```

Review all Python, XML, JavaScript, SCSS, ACLs, record rules, cron records,
schemas, shell scripts, Docker instructions, and Compose overlays. Do not
weaken security rules merely to make a test pass.

## 6. Immutable image build

The Dockerfile base image must remain digest-pinned. Build from a clean exact
head. The local build is for validation only:

```bash
PUSH=false deploy/odoo/call-followup-release/build.sh
```

For a registry release candidate, authenticate to GHCR using the approved
operator process, then run:

```bash
PUSH=true \
  IMAGE_REPOSITORY=ghcr.io/appolon1908-hue/codestra-odoo-call-followup \
  deploy/odoo/call-followup-release/build.sh
```

Capture the emitted immutable image reference in this form:

```text
repository@sha256:<64 lowercase hexadecimal characters>
```

Release evidence must include:

- clean source SHA;
- image tag used for the build;
- immutable image digest;
- base-image digest;
- OCI source and revision labels;
- embedded `/opt/codestra/release/call-followup-manifest.json`;
- all four addon directories under `/opt/codestra/addons`;
- SBOM;
- max-mode provenance;
- approved vulnerability scan result;
- signature or protected attestation evidence when the repository signing
  workflow is available;
- builder identity and UTC timestamp.

Never use a mutable tag as deployment evidence.

## 7. Disposable Odoo 19 database

Before staging, create an isolated PostgreSQL database and matching temporary
filestore. Do not connect it to production volumes, production SMTP, production
middleware, or a provider network.

Install all four modules from the candidate image with tests enabled:

```text
codestra_crm_call_followup
codestra_crm_call_followup_api
codestra_crm_call_followup_ux
codestra_crm_call_followup_automation
```

The disposable test passes only when:

- the Odoo registry loads;
- all views compile;
- backend assets compile;
- ACLs and record rules load;
- calendar alarms and mail templates load;
- cron records load;
- every addon test passes;
- a subsequent module upgrade passes;
- automation delivery remains disabled;
- the container healthcheck passes;
- no external request occurs;
- the database and filestore can be destroyed after sanitized evidence is
  captured.

## 8. Staging inventory and backups

Inventory the actual staging host before changing it. Record:

- current repository directory, branch, and SHA;
- current Odoo image digest;
- Odoo and PostgreSQL versions;
- exact Compose project and Compose files;
- target database;
- filestore path or volume;
- web, worker, cron, and bus topology;
- outgoing mail server identity;
- middleware endpoint and current automation flag;
- available disk space;
- current health and restart state;
- rollback owner.

Create and verify a PostgreSQL backup and the matching filestore backup before
module installation or upgrade. Record immutable backup identifiers and prove
that both artifacts are readable.

## 9. Staging Docker installation or upgrade

Use an explicit staging Compose base. Never rely on the production default in
staging.

```bash
export BASE_COMPOSE_FILES="<staging-base>:<staging-override>"
export ODOO_CALL_FOLLOWUP_IMAGE="<repository>@sha256:<digest>"
export ODOO_CALL_FOLLOWUP_RELEASE_SHA="<exact-docker-branch-sha>"
export APPROVED_HEAD_SHA="$ODOO_CALL_FOLLOWUP_RELEASE_SHA"
export ODOO_DATABASE="<staging-database>"
export MODULE_OPERATION=install
export DATABASE_BACKUP_ID="<verified-staging-database-backup>"
export FILESTORE_BACKUP_ID="<verified-staging-filestore-backup>"
export INCLUDE_AUTOMATION_SECRETS=NO

deploy/odoo/call-followup-release/deploy.sh staging
```

Use `MODULE_OPERATION=upgrade` only when all four modules are already installed
at an earlier reviewed version. The deployment script must stop Odoo, run the
one-shot module operation, and start Odoo only after that operation succeeds.
A failed operation must leave Odoo stopped and require rollback or reviewed
repair.

## 10. Optional staging automation configuration

Mount only synthetic staging credentials through Docker secrets or the approved
secret manager. Do not store their host paths or values in Git. The deployment
process expects the two secret-file environment variables documented in
`compose.automation-secrets.yaml`.

Configure these Odoo parameters through an audited Odoo shell or approved
configuration process:

```text
codestra.call_followup_automation.target_url
codestra.call_followup_automation.allowed_hosts
codestra.call_followup_automation.tenant_id
codestra.call_followup_automation.api_key_file
codestra.call_followup_automation.webhook_secret_file
codestra.call_followup_automation.timeout_seconds
codestra.call_followup_automation.enabled
```

Requirements:

- the target uses HTTPS except an explicitly approved loopback test;
- `allowed_hosts` contains the one exact middleware hostname and no wildcard;
- the API key and HMAC secret are mounted as regular files;
- the HMAC secret meets the addon minimum length;
- `codestra.call_followup_automation.enabled` remains `False` until all
  disabled-mode tests pass;
- mounting secrets alone does not authorize delivery.

## 11. Staging acceptance

Use synthetic CRM contacts, synthetic call IDs, and test mailboxes only.

### Core forms and CTAs

Verify:

- an authenticated completed-call event opens the modal only for the assigned
  logged-in agent;
- Outcome, Notes, Schedule, and Email areas render correctly;
- required fields and validation messages are clear;
- Save & Complete works;
- Send Email & Complete queues the email and completes the call action;
- Schedule & Complete creates the correct next step;
- Complete Without Email works;
- Open CRM and Open Customer navigate to the intended records;
- callback and appointment creation work;
- calendar reschedule and cancellation synchronize back to the follow-up;
- the 30-minute agent in-app reminder is created;
- separate 15-minute client and agent emails are queued;
- SMTP failure leaves mail available for normal retry;
- CRM chatter and call history are correct;
- the layout is usable on desktop and narrow/mobile widths.

### UX snooze and recovery

Verify:

- 5-, 15-, and 30-minute snooze options;
- a persistent form snooze reloads the record instead of attempting to close
  the full form;
- a modal snooze closes only the dialog;
- future snoozes are excluded from startup reconciliation;
- the cron releases each due snooze once;
- closing an unfinished modal allows it to return without two active dialogs;
- browser offline/online recovery works;
- periodic pending reconciliation works;
- another agent cannot read, snooze, or complete the record.

### API v1

Verify:

- service API-key authentication;
- validation-only calls do not create records;
- a valid event is accepted;
- same company/event/payload replay returns the original record and
  `replayed=true`;
- a retry may use a different correlation ID;
- a changed immutable payload under the same key is rejected;
- unknown fields are rejected;
- invalid time ordering is rejected;
- company, agent, lead, and customer mismatches are rejected;
- status reconciliation succeeds after a simulated client timeout;
- capabilities are machine-readable;
- the middleware reference client uses bounded timeout and retry.

### Durable automation with delivery disabled

Verify:

- completion appends immutable outbox events in the same database transaction;
- no remote request occurs;
- duplicate completion creates no duplicate event;
- calendar mutation keys are payload-hash based;
- payloads exclude notes, email bodies, recipient addresses, recordings,
  credentials, and raw provider payloads;
- managers can inspect events but cannot directly edit or delete them;
- another company cannot read them;
- automation status reports disabled.

### Synthetic middleware delivery

Only after disabled-mode acceptance, enable delivery against one approved
synthetic middleware endpoint and verify:

- exact host allowlist enforcement;
- redirect rejection;
- timestamp and HMAC validation;
- API-key authentication;
- idempotency and correlation headers;
- response-size limits;
- bounded network timeout;
- two workers cannot claim the same row;
- stale processing leases can be reclaimed;
- an older worker cannot overwrite a newer lease result;
- transport, 408, 429, and 5xx failures retry;
- permanent 3xx and non-retryable 4xx responses dead-letter;
- retry exhaustion dead-letters;
- Retry Now preserves lifetime attempt evidence and adds only the bounded manual
  retry budget;
- Move to Dead Letter works only in an allowed state;
- downstream n8n workflows remain inactive unless separately approved.

Disable automation delivery again after staging acceptance.

## 12. Observability and rollback rehearsal

Verify and record:

- Odoo web health;
- worker and cron health;
- bus/websocket delivery;
- PostgreSQL locks, connections, and error rate;
- mail queue health;
- container restart count;
- CPU and memory;
- outbox pending, processing, retry, delivered, and dead counts;
- secret and PII redaction in logs;
- dead-letter alerting;
- rollback owner notification.

Rehearse the complete rollback in staging. When modules changed schema or data,
stop Odoo, restore the matching PostgreSQL and filestore backups, restore the
previous app SHA and image digest, start Odoo, validate registry/web/bus/cron/
mail health, and reconcile retained middleware events.

## 13. Production GO/NO-GO

Production remains `NO_GO` until every value below is true:

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
IMAGE_SIGNATURE_OR_PROTECTED_ATTESTATION=PASS
DISPOSABLE_INSTALL=PASS
DISPOSABLE_UPGRADE=PASS
STAGING_INSTALL_OR_UPGRADE=PASS
ODOO_TESTS=PASS
API_ACCEPTANCE=PASS
POPUP_FORM_AND_CTA_ACCEPTANCE=PASS
CALENDAR_AND_REMINDER_ACCEPTANCE=PASS
MAIL_QUEUE_ACCEPTANCE=PASS
UX_SNOOZE_AND_RECOVERY=PASS
OUTBOX_RETRY_AND_DEAD_LETTER=PASS
MULTI_COMPANY_ISOLATION=PASS
DATABASE_BACKUP=VERIFIED
FILESTORE_BACKUP=VERIFIED
ROLLBACK_REHEARSAL=PASS
MONITORING_AND_ALERTS=PASS
CHANGE_WINDOW=APPROVED
```

## 14. Production deployment

After all gates pass, set the required variables through the approved operator
shell or secret manager. Use the exact protected final SHA and immutable image
digest. The deployment command is:

```bash
deploy/odoo/call-followup-release/deploy.sh production
```

The production environment must provide:

```text
BASE_COMPOSE_FILES
ODOO_CALL_FOLLOWUP_IMAGE
ODOO_CALL_FOLLOWUP_RELEASE_SHA
APPROVED_HEAD_SHA
ODOO_DATABASE
MODULE_OPERATION
DATABASE_BACKUP_ID
FILESTORE_BACKUP_ID
REQUIRED_CHECKS=PASS
INDEPENDENT_REVIEW=APPROVED
STAGING_ACCEPTANCE=PASS
ROLLBACK_REHEARSAL=PASS
CHANGE_ID
ROLLBACK_IMAGE
ROLLBACK_APP_SHA
ALLOW_PRODUCTION_DEPLOY=YES
PRODUCTION_CONFIRMATION=DEPLOY <exact approved SHA>
INCLUDE_AUTOMATION_SECRETS=NO
```

The script pulls the exact digest, stops Odoo, runs the one-shot install or
upgrade, starts Odoo, checks health, and writes evidence. It does not declare
production complete.

## 15. Production canary

Keep remote automation delivery disabled. Assign the feature to one approved
canary agent. Use a synthetic completed-call event rather than placing a live
call solely for deployment testing.

Repeat the popup, form, CTA, CRM/customer navigation, email queue, callback,
calendar, reminders, bus recovery, snooze, ACL, idempotency, and audit checks.
Monitor Odoo, PostgreSQL, bus, mail, container, and host health. Expand access
only after signed canary acceptance.

Remote automation activation is a separate production change requiring its own
middleware HMAC, host policy, retry, dead-letter, monitoring, rollback, and
approval evidence.

## 16. Final report

Return a complete evidence-backed report containing:

1. current directory;
2. repository and branch;
3. starting and final SHAs;
4. commits created;
5. source PR states and merge SHAs;
6. Docker PR state and exact head;
7. image tag and immutable digest;
8. base-image digest;
9. SBOM, provenance, scan, and signature/attestation evidence;
10. Compose project and files used;
11. database and filestore backup identifiers;
12. module operation command and result;
13. installed module versions and states;
14. source/static test results;
15. disposable install and upgrade results;
16. API acceptance results;
17. popup, form, and CTA results;
18. calendar and reminder results;
19. mail queue and retry results;
20. UX snooze and reconnect results;
21. outbox, lease, retry, and dead-letter results;
22. multi-company and authorization evidence;
23. container, Odoo, database, bus, cron, and mail health;
24. rollback rehearsal and exact rollback procedure;
25. unresolved blockers;
26. `MERGED=YES|NO`;
27. `PRODUCTION_DEPLOYED=YES|NO`;
28. `AUTOMATION_REMOTE_DELIVERY_ENABLED=YES|NO`.

Do not claim a pass without the command output and runtime evidence supporting
it.
