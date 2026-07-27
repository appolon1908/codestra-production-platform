# Codestra Server B Implementation Instructions for Codex

## Purpose

Complete the Server B telephony and adapter platform professionally, safely, and autonomously.

Server B is the authoritative telephony system. It must provide secure, tested adapters to Server A without enabling production traffic, placing live calls, activating carriers, changing public DIDs, processing customer recordings, or weakening the current fail-closed state.

This instruction contains no implementation code. Codex must inspect the installed environment, select compatible implementation methods, install only what is genuinely missing, correct defects, test every requirement, and continue until the authorized Server B engineering scope is complete or a true external blocker is proven.

---

# 1. Server Identity and Responsibility

## Server B

- Public IP: `65.21.67.207`
- Private IP: `10.40.0.2`
- Role: VICIdial, Asterisk, MariaDB, telephony adapters, telephony events, recordings, endpoint provisioning, and read-back verification

## Server A

- Public IP: `65.109.65.169`
- Private IP: `10.40.0.1`
- Role: Odoo 19, middleware, PostgreSQL, Redis, Keycloak, n8n, AI, WebSockets, reporting, NATS JetStream, Temporal, governance, and release evidence

## Server Boundary

Server B owns telephony truth.

Server B must not become the owner of:

- Odoo business logic
- AI provider routing
- AI prompt management
- n8n workflow decisions
- reporting calculations
- customer lifecycle logic
- Temporal business workflows
- NATS server infrastructure
- production feature-flag approval

Server B may publish canonical events or call Server A private APIs through approved service identities.

---

# 2. Full Engineering Authorization

Codex is authorized to:

- inspect all Server B repositories, services, databases, adapters, and configurations
- install required staging packages
- create private-only staging services
- implement or repair Server B adapters
- create staging schemas or test fixtures
- create inactive synthetic VICIdial campaigns, users, groups, queues, and endpoints
- create backups after the safety baseline passes
- run unit, integration, security, performance, recovery, and rollback tests
- restart only services inside the authorized milestone
- correct defects and rerun tests
- create clean commits
- generate protected evidence and checksums
- continue autonomously through routine engineering decisions

Codex must stop only for a true external prerequisite or an action outside this authorization.

---

# 3. Actions Not Authorized

Codex must not:

- place or answer live external calls
- activate carriers
- activate public DIDs
- enable predictive dialing
- activate production campaigns
- pause or resume production agents
- create or register production endpoints
- process customer recordings or customer audio
- send production events
- perform historical event backfill
- process quarantined historical event queues
- expose MariaDB, Asterisk administration, recordings, or adapter APIs publicly
- modify Server A directly
- enable production feature flags
- claim production readiness

---

# 4. Mandatory Safe State

The following must remain true before, during, and after implementation:

- `codestra-vicidial-sync.service` remains disabled and inactive
- persistent event delivery remains disabled
- `SEND_EVENTS` remains false
- historical backfill remains false
- production VICIdial writes remain false
- live audio remains false
- production transcription remains false
- production AI remains false
- production IVR routing remains false
- production callbacks remain false
- production endpoint provisioning remains false
- production traffic remains false

Final-state counters must show:

- live calls placed: zero
- live calls answered: zero
- customer audio processed: zero
- customer recordings processed: zero
- public DIDs activated: zero
- carriers activated: no
- production events sent: zero
- production rows changed: zero, except explicitly approved isolated staging records
- external endpoints registered: zero

---

# 5. Authoritative Specifications

Before implementation, Codex must confirm that the authoritative completion specifications are available.

The required specifications are:

1. Cross-Server Completion, Acceptance, and Production-Gate Plan
2. Missing Automation, AI API, and Webhook Architecture
3. Server B adapter, IVR, appointment, reporting, transcription, and low-latency specifications
4. The most recent accepted evidence and final reports

Codex must:

- verify file integrity
- record checksums
- reject competing drafts as authoritative
- treat unverified pasted text only as reference material
- stop fail-closed when required authoritative specifications are missing

Do not begin implementation based only on an unauthenticated pasted copy.

---

# 6. Exclusive Locking Requirements

Use the Server B project-local lock root:

`/root/vicidial-sync-remediation/.locks`

The milestone lock must:

- be on a persistent host-visible filesystem
- be owned by root
- use restrictive permissions
- be a regular file
- not be a symbolic link
- use a kernel-level exclusive lock
- remain held by the same process for the entire milestone
- fail immediately when already held
- be releasable automatically when the process exits
- pass a two-process contention test

Do not use `/run/lock` when it is read-only.

Do not use `/tmp`.

Do not continue without a verified lock.

The kernel lock result is authoritative. Process-inspection tools may be used only as supplementary information.

Codex must protect against lock-path substitution and symbolic-link races. It must not truncate an existing lock file as part of acquisition.

---

# 7. Baseline Evidence Requirements

Codex must complete the full baseline before creating backups, installing packages, changing configurations, or starting implementation.

The baseline must record:

- current user and execution environment
- host or container scope
- filesystem and mount scope
- repository paths, branches, commits, and dirty state
- service states
- container names, images, versions, and digests
- VICIdial version
- Asterisk version and modules
- Apache version
- MariaDB version and schemas
- campaigns, inbound groups, users, endpoints, DIDs, and carriers using aggregate counts
- active calls
- active channels
- endpoint registrations
- carrier state
- synchronization-service state
- actual production feature-flag values
- public and private listeners
- adapter endpoints
- recording services
- current evidence and rollback assets

The baseline must never infer a safe value from a failed command.

A failed or unavailable telephony command must produce `UNKNOWN`, not zero.

Any `UNKNOWN` value affecting safety must block implementation until resolved.

---

# 8. Corrections Required in the Baseline Procedure

Codex must apply all of the following rules.

## 8.1 Evidence Metadata

Generated evidence metadata must contain resolved values.

Do not write literal variable expressions, command substitutions, or unresolved placeholders into the evidence manifest.

Each field must be generated explicitly and verified.

## 8.2 Synchronization-Service State

Read the synchronization-service state directly from the service manager.

Do not rely on chained text searches that suppress output.

An active synchronization service is a blocking failure.

## 8.3 Lock Ownership

Treat the kernel lock as authoritative.

Do not require `lsof` or a process-listing result to prove lock ownership.

## 8.4 Lock Race Protection

Create and validate the protected lock path before opening it.

Reject symbolic links, unexpected owners, unsafe permissions, or a changed path identity.

Do not truncate the lock file.

## 8.5 Asterisk and VICIdial State

Do not rely on one fixed output format.

Codex must detect the installed Asterisk channel driver and version, select appropriate read-only commands or APIs, validate command success, and record raw sanitized evidence.

A command failure must block the baseline.

## 8.6 Process Evidence

Do not collect unrestricted process command lines.

Record only:

- approved service names
- service states
- aggregate process counts
- process identifiers when required for service verification

Do not expose secrets passed in command-line arguments.

## 8.7 Backup Timing

Do not create backups before all baseline safety checks pass.

After the baseline passes:

- create focused backups
- checksum every backup
- generate a backup manifest
- verify restore or read-back where safe
- handle empty directories and file sets safely

## 8.8 Unattended Execution

Do not pause for interactive input while holding the lock.

Use explicit scope authorization and proceed autonomously.

When a phase requires separate authorization, stop cleanly after releasing resources and writing evidence.

## 8.9 Actual Feature Flags

Read every actual authoritative feature flag.

Do not write expected values into evidence as though they were observed values.

At minimum verify:

- production traffic
- VICIdial writes
- campaign synchronization
- agent synchronization
- lead publication
- endpoint provisioning
- IVR routing
- IVR callbacks
- appointment auto-pause
- live audio
- live transcription
- real-time AI
- post-call AI
- event delivery
- historical backfill

## 8.10 Carriers, Registrations, Channels, and Endpoints

Verify these through installed authoritative interfaces.

Do not translate unavailable tools or failed commands into zero.

Any unresolved active-carrier, channel, registration, or endpoint state blocks implementation.

---

# 9. Requirements Traceability Review

Codex must compare every Server B requirement against the actual installed platform.

Each item must be classified as:

- Implemented and tested
- Implemented but not tested
- Partially implemented
- Missing
- Conflicting implementation
- Obsolete implementation
- Blocked by external prerequisite
- Live acceptance required

Each traceability item must record:

- requirement
- authoritative source
- responsible adapter or service
- implementation path
- current behavior
- current tests
- current evidence
- identified gap
- remediation performed
- final result
- final evidence
- remaining blocker

Do not accept filenames, comments, or old reports as proof.

---

# 10. Authoritative Server B Adapter Package

Codex must produce one maintained Server B adapter package.

It must include:

- reporting adapter
- reporting snapshot adapter
- IVR adapter
- queue adapter
- callback adapter
- APPT_PREP pause and resume adapter
- agent provisioning adapter
- endpoint provisioning adapter
- offboarding and revocation adapter
- recording-reference service
- telephony event gateway
- event delivery client
- health and readiness
- metrics
- audit
- reconciliation
- read-back verification
- rollback procedures

Codex must:

- identify competing implementations
- choose the authoritative implementation
- preserve unreviewed code
- archive superseded code only after review
- record provenance
- eliminate active conflicts
- maintain one versioned API contract

---

# 11. Private Security Boundary

All Server B adapter services must:

- bind only to loopback or `10.40.0.2`
- accept only approved Server A service identities
- use mTLS
- validate service authorization
- validate environment
- validate business unit
- validate campaign
- enforce strict schemas
- require correlation and idempotency identifiers
- rate limit requests
- create audit records
- mask secrets
- expose safe errors
- reject direct browser access

The adapter must not expose:

- arbitrary SQL
- unrestricted database access
- raw database errors
- SIP passwords
- administrative credentials
- recording directories
- permanent recording URLs
- private keys
- customer fields outside approved schemas

---

# 12. Reporting and Snapshot Adapter

The reporting adapter must provide normalized, read-only access to:

- inbound calls
- outbound calls
- queue entries
- abandoned calls
- agent sessions
- login and logout events
- pause events
- call durations
- dispositions
- transfers
- callbacks
- campaign activity
- inbound-group activity
- recording references
- call identifiers
- agent identifiers
- campaign identifiers

Requirements:

- documented authoritative source tables or views
- finalized-record predicates
- deterministic ordering
- deterministic watermarks
- bounded time windows
- pagination
- field allowlists
- data masking
- read-only database identity
- reviewed query plans
- query-duration limits
- concurrency limits
- throttling under telephony pressure
- no dependence on the legacy event queue
- no unbounded historical scan
- read-back and payload hashes
- no impact on live call processing

---

# 13. Real-Time Telephony Event Gateway

Codex must create or reconcile one persistent telephony event gateway.

It must use an installed and approved Asterisk real-time interface.

It must not depend on second-by-second MariaDB polling for live events.

The gateway must normalize:

- agent login
- agent Ready
- agent pause
- call created
- ringing
- answered
- assignment
- customer connected
- hold
- resume
- transfer
- conference
- hangup
- recording started
- recording stopped
- endpoint registered
- endpoint unregistered

Every event must contain:

- schema version
- event ID
- UniqueID
- LinkedID where applicable
- sequence
- business unit
- campaign
- agent
- endpoint
- timestamp
- request and correlation identifiers
- idempotency key
- environment
- data classification

Production event delivery must remain disabled.

Synthetic event delivery must be bounded, temporary, auditable, and revoked after testing.

---

# 14. IVR, Queue, and Callback Adapter

Codex must implement or reconcile:

- DID resolution
- business-unit resolution
- campaign resolution
- language selection
- menu policy
- inbound-group validation
- queue state
- agent availability
- after-hours policy
- holiday policy
- overflow policy
- failure fallback
- callback creation
- callback publication
- callback read-back
- IVR-session read-back

Requirements:

- campaign lock after operational routing
- same-campaign transfer rules
- controlled wrong-selection reclassification
- idempotent callback publication
- synthetic DIDs and inactive test routes
- no test context attached to public trunks
- no live inbound calls

---

# 15. APPT_PREP Adapter

Codex must implement or reconcile:

- appointment readiness
- agent telephony-state read
- pause request
- pause-pending state
- pause confirmation
- resume request
- resume confirmation
- same-campaign validation
- appointment validation
- audit
- idempotency

Required behavior:

- an active call is never interrupted
- a busy agent enters pause-pending state
- `APPT_PREP` is applied only when safe
- Odoo may show paused only after read-back confirmation
- resume requires a valid appointment outcome
- resume must preserve the assigned campaign and inbound groups
- all testing uses synthetic agents and inactive campaigns

---

# 16. Agent and Endpoint Provisioning

Codex must implement or reconcile private staging APIs for:

- creating or updating a test VICIdial user
- applying a test user group
- applying campaign permissions
- applying inbound groups
- assigning a staging endpoint
- returning a one-time credential reference
- read-back
- disabling and revoking the user
- revoking the endpoint
- reconciliation

Requirements:

- dedicated provisioning lock
- test namespace
- transactional compensation
- idempotency
- one-time secret retrieval
- no plaintext secret in Odoo, email, logs, reports, or evidence
- inactive campaign
- unregistered endpoint at final state
- complete offboarding
- preservation of historical attribution

No production user or endpoint may be modified.

---

# 17. Recording and Audio References

Codex must implement or reconcile:

- call and leg mapping
- participant mapping
- recording finalization
- recording version
- checksum
- consent state
- retention class
- access classification
- opaque recording reference
- short-lived access reference
- audit

The service must not expose:

- raw filesystem paths
- public media
- permanent URLs
- directory listings
- unrestricted audio
- unrelated customer data

A future audio source adapter may be prepared only in an inactive state.

Only synthetic audio may be used.

Raw media must not pass through n8n.

---

# 18. Event Backbone Client

NATS JetStream and Temporal belong to Server A.

Server B must not deploy a competing NATS or Temporal platform.

Server B may implement the approved event publisher or middleware client.

Requirements:

- canonical schema validation
- approved service identity
- business-unit and campaign scope
- message IDs
- deduplication
- acknowledgment
- bounded local spool
- circuit breaker
- backpressure
- replay-safe behavior
- telemetry
- no production publisher enabled
- no historical replay
- no accepted synthetic event loss

Telephony processing always has priority over reporting, AI, transcription, or event delivery.

---

# 19. Configuration and Database Safety

For every database query:

- use read-only access where possible
- use bounded windows
- use reviewed indexes
- review execution plans
- impose duration limits
- impose concurrency limits
- throttle when telephony latency increases
- avoid full-table scans
- avoid locks affecting call processing

For every Asterisk or VICIdial configuration change:

- create a focused candidate
- preserve the previous configuration
- produce a focused difference
- validate syntax
- test in an inactive namespace
- create rollback material
- avoid unrelated changes
- do not attach test configuration to live routes
- do not reload a production service without a proven need and scoped authorization

---

# 20. Required Tests

Codex must run and preserve raw evidence for:

## Baseline and Safety

- lock contention
- service-state validation
- feature-flag validation
- active calls
- active channels
- registrations
- carriers
- external endpoints
- public listeners

## Contracts and Security

- schema validation
- valid mTLS identity
- expired identity
- revoked identity
- wrong service
- wrong environment
- wrong business unit
- wrong campaign
- replay
- idempotency conflict
- direct browser denial
- rate limits
- secret scans
- log redaction

## Reporting

- every source contract
- finalized predicates
- cursors and watermarks
- pagination
- query plans
- high-volume reads
- call-processing impact
- reconciliation

## Telephony Events

- sequencing
- duplicates
- out-of-order events
- missing sequence
- gateway restart
- Server A unavailable
- local spool
- recovery
- backpressure
- retry storm prevention

## IVR and Callbacks

- every synthetic route
- language selection
- same-campaign lock
- wrong-selection correction
- callback duplicate protection
- after-hours
- holiday
- overflow
- queue failure
- read-back

## Appointments

- Ready to APPT_PREP
- active-call protection
- pause-pending
- pause confirmation
- duplicate pause
- resume
- duplicate resume
- same-campaign validation
- read-back

## Provisioning

- create
- duplicate create
- concurrent create
- compensation
- one-time secret retrieval
- expiration
- endpoint assignment
- read-back
- revocation
- offboarding
- reconciliation

## Recording References

- correct business unit
- correct campaign
- expired reference
- wrong identity
- no path exposure
- no public access
- audit

## Load and Recovery

- concurrent adapter requests
- snapshot bursts
- event bursts
- callback bursts
- Server A outage
- MariaDB latency
- Asterisk event-gateway restart
- adapter restart
- disk pressure
- bounded spool
- rollback

Every PASS must include:

- expected result
- actual result
- raw sanitized output
- timestamp
- environment
- source revision
- test version
- evidence path

---

# 21. Autonomous Defect Correction

Codex must fix defects autonomously.

After each correction:

1. Run the focused test.
2. Run affected integration tests.
3. Run security regression.
4. Run failure and recovery regression.
5. Rerun the complete Server B acceptance suite before claiming PASS.

Codex must not claim PASS when:

- evidence is missing
- a command failed and was interpreted as zero
- a state is unknown
- a checksum is missing
- a baseline value is contradictory
- an adapter has placeholder behavior
- an unsafe public listener exists
- an unreviewed production difference exists
- a rollback was not tested
- production flags changed
- synthetic credentials remain active

---

# 22. Final Safe State

At completion, Codex must confirm:

- synchronization service disabled and inactive
- persistent event delivery false
- all production feature flags false
- all test campaigns inactive
- all test DIDs detached
- all test endpoints unregistered or revoked
- all temporary credentials revoked
- carriers unchanged
- no active test calls or channels
- no customer audio or recordings processed
- no production events sent
- no historical backfill
- no public internal adapter listener
- evidence and rollback complete

---

# 23. Required Final Report

Codex must return:

## Overall Status

- Server B implementation status
- authoritative adapter package status
- baseline safe-state status
- requirements traced
- requirements implemented and tested
- requirements missing
- requirements blocked externally
- conflicting implementations

## Lock and Evidence

- lock path
- lock acquired
- lock contention passed
- full-process lock lifetime passed
- previous evidence preserved
- new evidence directory
- evidence checksum manifest
- final report checksum

## Security

- private API security
- mTLS
- service authorization
- business-unit isolation
- campaign isolation
- replay protection
- secret scan
- public internal listeners
- critical and high findings

## Adapters

- reporting adapter
- snapshot adapter
- telephony event gateway
- IVR adapter
- queue adapter
- callback adapter
- APPT_PREP adapter
- provisioning adapter
- endpoint provisioning
- offboarding
- recording-reference service
- read-back verification

## Reliability

- deterministic watermarks
- event sequencing
- duplicate side effects
- accepted synthetic event loss
- local-spool recovery
- retry storm
- rollback

## Tests

- total tests
- failures
- security failures
- load failures
- recovery failures
- unknown baseline values
- unresolved reconciliation gaps

## Final Invariance

- production rows changed
- live calls placed
- live calls answered
- customer audio processed
- customer recordings processed
- public DIDs activated
- carriers activated
- external endpoints registered
- production events sent
- production flags true
- production readiness

The only acceptable final production-readiness value for this scope is:

`PRODUCTION_READY=NO`

Production activation remains a separate formal authorization.

---

# 24. Paste-Ready Codex Instruction

## Server B Implementation Mandate

Proceed autonomously with the full Server B implementation described in this document.

Treat the current installed environment as the baseline.

Do not deploy draft code or create duplicate platform stacks.

Verify the authoritative specifications and safe state first.

Use the project-local exclusive lock and hold it for the full milestone.

Apply every baseline correction described in this document.

Implement or repair one authoritative Server B adapter package covering reporting, snapshots, telephony events, IVR, queues, callbacks, APPT_PREP, provisioning, endpoints, offboarding, recordings, read-back, audit, reconciliation, metrics, and rollback.

Install only compatible, pinned, private-only staging dependencies that are genuinely missing.

Use synthetic agents, campaigns, DIDs, queues, endpoints, callbacks, recordings, and events.

Do not place calls, activate carriers, activate public DIDs, register production endpoints, process customer media, enable production event delivery, modify production users, or perform historical backfill.

Run the complete test program.

Correct defects autonomously and rerun all affected tests.

Do not accept unknown states, missing evidence, placeholder behavior, unsafe listeners, duplicate side effects, event loss, or untested rollback.

Finish in the mandatory fail-closed state and return the complete evidence-backed final report.

Stop only for a verified external prerequisite or an action outside the authorization.
