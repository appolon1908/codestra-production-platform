# Codestra / Klyrow Master Production Activation Mission

## Mission

Take the existing Codestra email platform from its current controlled/canary state to a **certified, authorized, observable, reversible production state** across:

`Odoo / n8n -> Middleware -> Klyrow -> Postal/provider -> recipient -> provider event -> Middleware -> Odoo and n8n read-back`

This is a production-readiness and activation mission.

It is **not** a mail-server rebuild.

It is **not** a DNS rebuild.

It is **not** permission to replace working infrastructure.

Preserve existing working components and extend only what is missing.

---

## 1. Primary objective

Production is complete only when all of the following are true:

- transactional email can operate beyond the consumed one-message canary allowance;
- production mode remains fail-closed and explicitly authorized;
- Klyrow is the email delivery authority;
- Middleware is the platform orchestration/control plane;
- Odoo is the business system of record;
- n8n may orchestrate workflows but must not become the source of truth;
- DKIM security closeout is completed;
- end-to-end delivery and callbacks are proven;
- suppression, bounce, and complaint handling are proven;
- metering and idempotency are proven;
- fresh backup and restore are proven;
- rollback is rehearsed;
- exact production source is certified;
- observability and alerts are active;
- an explicit production authorization record exists;
- controlled rollout has succeeded;
- marketing/campaign email remains disabled until its separate compliance gate passes.

Target state:

`PRODUCTION_AUTHORIZED + TRANSACTIONAL_ACTIVE + OBSERVED + REVERSIBLE`

Campaign mode is separate.

---

## 2. Hard scope limits

Do not rebuild Postal/Klyrow mail infrastructure if it is already operating.

Do not redo ordinary SPF, MX, return-path, CNAME, A/AAAA, or basic DNS records that already pass merely because this production mission is running. Permit evidence-driven correction of failed SPF, MX, DMARC, alignment, and related DNS gates; preserve passing records and limit changes to the failing requirement.

Do not replace working SMTP credentials without cause.

Do not create a second email platform.

Do not create duplicate Odoo, Middleware, Klyrow, or n8n APIs when an equivalent route already exists.

Do not implement email-delivery logic inside Odoo that belongs in Middleware or Klyrow.

Do not move business truth into n8n.

Do not bypass protected branches, CI, CODEOWNER review, release policy, security checks, source-lock checks, signed-release requirements, or production authorization.

Do not call production complete from unit tests alone.

Do not silently enable campaigns.

Do not silently increase rate limits.

Do not permit unrestricted recipient delivery merely because transactional mode is enabled.

Do not claim an external provider action happened unless it was actually observed.

---

## 3. Required current-state reconciliation

Before changing code, inspect the exact heads of at least:

- `appolon1908-hue/klyrow.com`
- `appolon1908-hue/Middleware-`
- `appolon1908-hue/Odoo`
- `appolon1908-hue/codestra-production-platform`
- relevant n8n workflow/configuration source
- Keycloak where service authentication is involved
- Kong/Caddy where routing or TLS validation is involved

Inventory:

- existing email APIs;
- current safe/canary delivery modes;
- tenant authorization;
- sender-identity APIs;
- provider adapters;
- callback/webhook routes;
- idempotency;
- suppression;
- rate limits;
- metering;
- audit logging;
- Odoo outbound integration;
- Odoo delivery-status read-back;
- n8n email workflows;
- email observability metrics;
- release manifests;
- production source locks;
- kill switches.

Classify each requested capability as:

`EXISTS`, `PARTIAL`, `MISSING`, `DUPLICATE`, or `OBSOLETE`.

Do not create a new implementation before this inventory proves one is necessary. Remove or retire duplicate paths instead of maintaining two authorities.

---

## 4. Gate A - protected release chain

Resolve production/release blockers before any live activation.

Required outcome:

- no unresolved merge conflicts;
- branches rebased on required protected bases;
- no duplicate code introduced during conflict resolution;
- all exact-head required checks green;
- source-lock validation green;
- protected workflow/trust validation green;
- secrets scanning green;
- security review green where required;
- independent/CODEOWNER approval satisfied;
- production release SHA fixed and immutable.

Do not disable protected validators merely to make CI green.

Do not weaken exact-SHA validation.

Do not replace required CI with self-reported success.

The production-platform release must reference exact approved component revisions.

Create a release manifest containing at minimum:

- Odoo commit SHA;
- Middleware commit SHA;
- Klyrow commit SHA;
- production-platform commit SHA;
- Keycloak/config revision where relevant;
- image digests;
- configuration version;
- database migration version;
- release timestamp;
- release/change ID.

---

## 5. Gate B - post-canary transactional mode

The consumed one-message transactional canary must not be converted into an unsafe unlimited boolean.

Implement or complete a proper delivery policy supporting the functional equivalent of:

- `SAFE`
- `TRANSACTIONAL_CANARY`
- `TRANSACTIONAL_PRODUCTION`
- `CAMPAIGN_PRODUCTION`

Campaign mode remains unavailable until its separate gate passes.

Transactional production must require all of the following:

- global email service enabled;
- provider healthy;
- provider credential active;
- production authorization exists;
- authorization is not expired;
- tenant is approved;
- sending domain is approved;
- sender identity is approved;
- requested message type is permitted;
- recipient falls inside authorized scope;
- rate/volume limit is available;
- suppression check passes;
- idempotency check passes;
- global kill switch is open;
- tenant kill switch is open;
- sender/domain kill switch is open.

Any failed prerequisite must fail closed.

There must be no implicit fallback to unrestricted SMTP delivery.

---

## 6. Delivery policy data model

Use one authoritative production-delivery policy. Do not scatter production enablement across unrelated environment variables.

The policy must represent at least:

- `enabled`;
- `mode`;
- `tenant_id`;
- approved domains;
- approved sender identities;
- recipient scope;
- transaction categories;
- per-minute quota;
- per-hour quota;
- per-day quota;
- provider;
- authorization/change ID;
- valid-from;
- valid-until;
- approved-by;
- activated-by;
- kill-switch state;
- reason;
- environment;
- policy version.

Changes must be audited.

Only privileged production operators may change global production delivery state. Agents, supervisors, tenant users, workflow automation, and ordinary Odoo business users must not activate unrestricted production delivery.

---

## 7. API contract

Perform API inventory first and reuse current versioned APIs whenever they satisfy the requirement.

The platform must ultimately provide functional equivalents for:

- read current delivery policy;
- validate production readiness;
- authorize a production policy;
- activate transactional production;
- deactivate/revoke production;
- invoke emergency kill switch;
- inspect rate/quota state;
- inspect sender/domain authorization;
- inspect suppression state;
- inspect provider health;
- submit email;
- query message state;
- ingest provider delivery callbacks;
- query message events;
- inspect metering;
- inspect audit history.

Do not create two endpoints with different names that perform the same operation.

All mutations require:

- authenticated service/user identity;
- authorization;
- correlation ID;
- audit entry;
- idempotency where appropriate.

Provider callbacks require verification and replay protection.

---

## 8. Message identity contract

Every message must have one durable identity across the complete path.

Carry at minimum:

- `message_id`;
- `correlation_id`;
- `idempotency_key`;
- `tenant_id`;
- sender identity;
- recipient;
- template/message type;
- requested timestamp.

Trace this identity through:

`Odoo / n8n -> Middleware -> Klyrow -> provider -> callback -> Middleware event/projection -> Odoo and n8n read-back`

Do not regenerate a new correlation ID midway through the lifecycle.

Provider IDs are external identifiers attached to the platform `message_id`.

---

## 9. Idempotency

Production activation is blocked until duplicate-send protection is proven.

The same idempotency key with the same request must return the original logical result.

The same idempotency key with conflicting content must fail.

Repeated webhook events must not create repeated business effects.

Retrying a timeout must not silently generate multiple live emails.

Tests must cover:

- duplicate request;
- simultaneous duplicate request;
- retry after provider timeout;
- delayed callback;
- duplicate callback;
- out-of-order callback;
- process restart;
- queue retry.

---

## 10. DKIM security closeout

Preserve basic DNS records that already pass. Evidence-driven remediation of failed SPF, MX, DMARC, alignment, and related DNS gates is permitted; limit each change to the failing requirement and validate the corrected record.

Perform the required DKIM security remediation alongside the evidence-driven non-DKIM DNS remediation permitted above.

For every affected domain:

1. inventory current selector;
2. determine whether its private key was exposed or must be retired;
3. generate a new secure key;
4. create a new selector;
5. publish only the required DKIM record;
6. validate DNS visibility;
7. configure the sending system to use the new selector;
8. send a controlled validation message;
9. verify receiver-side DKIM passes;
10. retire/revoke the old key only after the new selector is verified;
11. document the transition.

Do not rotate all domains blindly in a single irreversible action.

Use controlled batches.

Produce a DKIM certification record for all 14 domains containing:

- domain;
- old selector;
- new selector;
- key fingerprint;
- rotation status;
- DNS verified;
- signing verified;
- old key revoked;
- certification timestamp.

Never place private DKIM material in Git, test output, issue comments, CI logs, or release artifacts.

---

## 11. End-to-end transactional canary

After the transactional-production mechanism exists but before general expansion, perform one owner-approved live canary.

Use an explicitly approved sender and recipient.

Prove the complete path:

`Odoo / n8n -> Middleware -> Klyrow -> provider -> recipient -> provider event -> Middleware -> Odoo and n8n read-back`

Capture evidence of:

- accepted request;
- authorization decision;
- quota decision;
- idempotency record;
- Klyrow acceptance;
- provider acceptance;
- provider message ID;
- recipient receipt;
- SPF result;
- DKIM result;
- DMARC result;
- return-path;
- correlation/message identity;
- delivery callback;
- Middleware event;
- Odoo final state;
- metering increment.

One logical email must equal one metered send.

---

## 12. Bounce, complaint, and suppression certification

Production cannot rely only on successful-delivery testing.

Prove handling for:

- hard bounce;
- soft bounce;
- complaint;
- unsubscribe where applicable;
- suppressed recipient;
- invalid sender;
- rejected domain;
- quota exhaustion.

Use approved test mechanisms or controlled test addresses where possible.

Do not intentionally send unsolicited messages to real users as a test.

After a hard-bounce or complaint suppression event, another send attempt must fail before reaching the external provider when suppression policy requires it.

Suppression reason and origin must be visible to authorized operators.

---

## 13. Odoo read-back

Odoo must not report `sent` merely because the request left Odoo.

Expose clear states such as:

- `requested`;
- `accepted`;
- `queued`;
- `provider_accepted`;
- `delivered`;
- `deferred`;
- `bounced`;
- `complained`;
- `suppressed`;
- `rejected`;
- `failed`.

Refresh/re-login must preserve final state because status must come from durable backend data, not browser memory.

Odoo must display the final result received through the control plane. Do not create a second mail lifecycle database inside the UI.

---

## 14. n8n boundary

n8n may orchestrate:

- workflow sequencing;
- template/data preparation;
- downstream business actions;
- notifications.

n8n must not become the authority for:

- production authorization;
- tenant RBAC;
- sender permissions;
- quotas;
- suppression truth;
- delivery policy;
- billing/metering truth;
- provider lifecycle truth.

A disabled or restarted n8n instance must not cause duplicated email delivery.

---

## 15. Campaign email stays closed

Transactional production does **not** authorize marketing.

Campaign mode remains disabled until all campaign-specific requirements pass:

- documented recipient consent model;
- tenant isolation;
- suppression enforcement;
- unsubscribe enforcement;
- unsubscribe propagation test;
- complaint handling;
- bounce handling;
- sender identity validation;
- campaign quota;
- daily volume ceiling;
- throttling;
- reputation monitoring;
- audit trail;
- template/content controls;
- explicit campaign authorization.

Never infer marketing permission from CRM membership or possession of an email address.

---

## 16. Observability

Production activation requires operational visibility before live expansion.

Expose metrics for at least:

- requests received;
- authorized sends;
- authorization denials;
- messages accepted;
- delivered;
- deferred;
- bounced;
- complained;
- suppressed;
- failed;
- provider latency;
- callback latency;
- callback failures;
- callback queue depth;
- idempotency replays;
- rate-limit denials;
- quota consumption;
- provider HTTP/SMTP errors;
- Klyrow errors;
- Middleware errors;
- Odoo synchronization errors.

Create alerts for abnormal:

- provider failures;
- callback backlog;
- bounce rate;
- complaint rate;
- authentication failures;
- authorization denials;
- 5xx errors;
- queue growth;
- suppression failures;
- delivery latency;
- missing callbacks.

Dashboards should identify environment, tenant, sending domain, sender, provider, and message category without exposing message bodies or secrets in labels.

---

## 17. Audit logging

Every privileged production operation must generate an immutable or append-only audit event.

Include:

- actor;
- timestamp;
- environment;
- action;
- resource;
- before state;
- after state;
- change ID;
- correlation ID;
- reason/result.

Audit at minimum:

- authorize production;
- revoke authorization;
- enable transactional mode;
- disable transactional mode;
- campaign enablement;
- sender approval;
- sender revocation;
- domain approval;
- quota changes;
- kill-switch activation;
- kill-switch reset.

---

## 18. Backup and restore certification

A backup existing is not enough.

Before final production activation:

1. create a fresh encrypted backup;
2. record SHA-256;
3. verify encryption;
4. verify archive integrity;
5. restore it into an isolated rehearsal environment;
6. start required services against restored data;
7. validate critical records;
8. prove restored email/audit state is readable;
9. record recovery duration and result.

Do not modify production during restore rehearsal.

Evidence must identify exactly which backup was restored.

---

## 19. Rollback rehearsal

Document and test rollback before launch.

Rollback must be able to:

- disable outbound email immediately;
- preserve inbound callbacks;
- preserve historical message state;
- preserve audit logs;
- restore previous application version;
- restore previous configuration;
- restore database when required;
- avoid duplicate message replays after rollback.

Emergency behavior should favor:

`STOP NEW SENDS, KEEP OBSERVABILITY AND CALLBACK INGESTION AVAILABLE`

Do not design a kill switch that destroys evidence required to diagnose the incident.

---

## 20. Production authorization record

Live transactional mode remains `NOT_AUTHORIZED` until an explicit production authorization record exists.

The record must include:

- production owner;
- change ID;
- approved tenant(s);
- approved domains;
- approved senders;
- approved message categories;
- approved recipient scope;
- per-minute limit;
- per-hour limit;
- per-day limit;
- launch window;
- monitoring owner;
- escalation owner;
- rollback owner;
- kill-switch procedure;
- approved release SHA;
- authorization timestamp;
- expiration/review date where required.

Application code must validate effective authorization rather than rely on a comment stating `approved`.

---

## 21. Production source certification

Before cutover certify the exact production source.

Required:

- protected release base;
- clean working tree;
- exact release SHA;
- no unresolved conflicts;
- all required checks green;
- required approvals present;
- release/source-lock green;
- secrets scan green;
- dependency/security checks complete;
- immutable image digest recorded;
- migration state recorded;
- release artifact signed/verified where required;
- rollback artifact available.

Historical CI against an older SHA is not sufficient.

---

## 22. Staging certification

Deploy the exact candidate to staging.

Do not certify staging using different source and silently deploy another production SHA.

Run:

- startup/health;
- authentication;
- Keycloak service auth;
- Kong routing;
- Odoo -> Middleware request;
- Middleware -> Klyrow;
- Klyrow/provider test path;
- callback ingestion;
- Odoo read-back;
- idempotency;
- suppression;
- quota;
- kill switch;
- recovery/restart;
- observability;
- alert tests.

Staging must be green before production authorization is exercised.

---

## 23. Controlled production rollout

Do not move from one canary directly to all 14 domains at full volume.

### P0 - Closed

Mode: `SAFE`

Complete certification. No general production sending.

### P1 - One sender / one domain

Activate transactional production only for one approved tenant, one approved domain, one or a very small set of approved senders, a tight recipient scope, and low quotas.

Verify delivery, callbacks, errors, reputation, bounce rate, complaint rate, latency, quotas, and audit logging.

### P2 - One domain transactional

Expand transactional sender coverage for the certified domain while maintaining limits.

### P3 - Multi-domain transactional

Expand approved domains in controlled batches. Never expand a failing batch.

### P4 - Full approved transactional scope

Enable all individually certified transactional domains/senders and continue monitoring.

### P5 - Campaign

Only after the separate campaign compliance gate and explicit campaign authorization.

Campaign production is not required to declare transactional email production-ready.

---

## 24. Automatic stop conditions

Stop expansion or disable new outbound sends if thresholds indicate abnormal behavior.

At minimum treat these as stop signals:

- unexplained large 5xx increase;
- provider rejection surge;
- callback processing failure;
- suppression bypass;
- idempotency failure;
- duplicate-send evidence;
- authentication/authorization bypass;
- unexpected tenant crossover;
- complaint-rate spike;
- bounce-rate spike;
- source/version mismatch;
- monitoring failure that makes safe operation unverifiable.

Prefer fail-closed behavior.

---

## 25. Security requirements

Never commit:

- SMTP passwords;
- API tokens;
- DKIM private keys;
- Keycloak secrets;
- Postal credentials;
- production recipient information;
- database passwords;
- backup encryption keys.

Use the existing secret authority/environment injection mechanism.

Ensure production APIs enforce service identity and RBAC.

Do not trust tenant/sender identity solely because it appears in request JSON.

Cross-tenant email access must fail.

---

## 26. Test matrix

### Authorization

- authorized sender succeeds;
- unauthorized sender fails;
- unauthorized domain fails;
- unauthorized tenant fails;
- expired authorization fails;
- disabled production mode fails.

### Quotas

- below quota succeeds;
- per-minute limit enforced;
- hourly limit enforced;
- daily limit enforced;
- tenant isolation maintained.

### Idempotency

- duplicate same request does not duplicate send;
- conflicting idempotency replay rejected;
- callback replay safe.

### Suppression

- suppressed recipient blocked;
- hard-bounce suppression enforced;
- complaint suppression enforced.

### Callbacks

- delivered;
- deferred;
- bounced;
- complained;
- duplicate event;
- out-of-order event;
- invalid signature;
- unknown message.

### Failure

- provider timeout;
- provider 4xx;
- provider 5xx;
- Klyrow unavailable;
- Middleware restart;
- Odoo unavailable during callback;
- n8n unavailable;
- queue restart.

### RBAC

- platform admin;
- platform operator;
- tenant admin;
- supervisor;
- agent;
- service account.

Only authorized production operators may alter global production delivery state.

---

## 27. Cleanup

As part of this mission:

- resolve relevant merge conflicts;
- rebase stale branches;
- eliminate duplicate implementation;
- retire obsolete feature flags;
- document deprecated endpoints;
- remove dead routes only after confirming no live caller depends on them;
- update API/OpenAPI documentation;
- update runbooks;
- update architecture documentation;
- update environment variable documentation;
- update rollback documentation;
- update operational dashboards.

Do not perform unrelated cosmetic refactors that increase cutover risk.

---

## 28. Required runbooks

Production must have runbooks for:

- normal transactional activation;
- emergency email shutdown;
- provider failure;
- callback backlog;
- bounce spike;
- complaint spike;
- DKIM failure;
- sender/domain revocation;
- quota adjustment;
- credential rotation;
- rollback;
- backup restore;
- re-enabling after incident.

Each runbook must identify the authoritative control surface.

---

## 29. Release evidence package

Create one production certification package containing:

- release/change ID;
- exact SHAs;
- image digests;
- CI results;
- approvals;
- release/source-lock result;
- staging results;
- DKIM certification;
- backup SHA;
- restore evidence;
- rollback evidence;
- authorization record;
- canary evidence;
- receiver authentication evidence;
- idempotency evidence;
- callback evidence;
- bounce/suppression evidence;
- metering evidence;
- dashboard identifiers/links;
- alert test evidence;
- production rollout state;
- known limitations.

Do not place secrets inside the evidence package.

---

## 30. Definition of done

Do not write `PRODUCTION COMPLETE` until all mandatory gates are genuinely proven.

Required final result:

```text
RELEASE_SOURCE_CERTIFIED=PASS
PROTECTED_CI=PASS
STAGING_CERTIFIED=PASS
DKIM_ROTATION_CERTIFIED=PASS
BACKUP_VERIFIED=PASS
RESTORE_REHEARSAL=PASS
ROLLBACK_REHEARSAL=PASS
PRODUCTION_AUTHORIZATION=ACTIVE
TRANSACTIONAL_POLICY=ACTIVE
E2E_CANARY=PASS
SPF=PASS
DKIM=PASS
DMARC=PASS
CALLBACKS=PASS
IDEMPOTENCY=PASS
METERING=PASS
BOUNCE_HANDLING=PASS
COMPLAINT_HANDLING=PASS
SUPPRESSION=PASS
OBSERVABILITY=PASS
KILL_SWITCH=VERIFIED
CONTROLLED_ROLLOUT=PASS
```

For marketing:

`CAMPAIGN_MODE=DISABLED`

is an acceptable and preferred production-launch result until separate campaign certification is complete.

---

## 31. Final status report format

At completion return exactly these sections.

### Production Status

State transactional email as one of:

- `NOT_AUTHORIZED`
- `AUTHORIZED_NOT_ACTIVE`
- `CANARY_ACTIVE`
- `LIMITED_PRODUCTION`
- `FULL_TRANSACTIONAL_PRODUCTION`

State campaign status separately.

### Changes

List repositories, PRs, commits, and affected components.

### APIs

List reused, changed, added, and deprecated routes.

### Security

Report authentication, authorization, secret handling, DKIM rotation, suppression, and tenant isolation.

### Certification

Report every production gate as PASS, FAIL, or BLOCKED.

### Canary

Report actual observed evidence without exposing sensitive recipient information.

### Release

Give exact production SHA/image digest/config version.

### Rollback

Give verified rollback and kill-switch actions.

### Remaining Blockers

List every unresolved blocker. Never hide a blocker to make the status look green.

---

## Final directive

Do not rebuild the mail server.

Do not redo working basic DNS.

Do not invent a parallel architecture.

Finish the existing architecture.

Close the missing post-canary transactional-production control.

Close the DKIM security issue.

Certify the complete Odoo -> Middleware -> n8n -> Klyrow -> provider -> callback -> Odoo lifecycle.

Certify backup, restore, rollback, source integrity, observability, authorization, and kill switches.

Launch transactional email gradually under explicit limits.

Keep marketing closed until its separate consent/suppression/unsubscribe/reputation requirements pass.

The objective is not simply to make email send.

The objective is to make production email **authorized, controlled, traceable, idempotent, secure, observable, reversible, and independently certifiable**.
