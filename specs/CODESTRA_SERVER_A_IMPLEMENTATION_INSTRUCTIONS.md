# Codestra Server A Implementation Instructions for Codex

## Purpose

Complete the Server A application, automation, AI, identity, reporting, and governance platform professionally, safely, and autonomously.

This document is for **Server A only**. It contains implementation instructions, responsibilities, acceptance gates, and required evidence. It contains no implementation code and no blanket deployment command.

Codex must inspect the current Server A environment, preserve accepted components, implement only missing or deficient functionality, install compatible staging dependencies where genuinely needed, test every requirement, correct defects, and continue until the authorized Server A engineering scope is complete or a true external blocker is proven.

---

# 1. Server Identity

## Server A

- Public IP: `65.109.65.169`
- Private IP: `10.40.0.1`
- Role: application and orchestration control plane

## Server B

- Public IP: `65.21.67.207`
- Private IP: `10.40.0.2`
- Role: VICIdial, Asterisk, MariaDB, telephony truth, telephony adapters, and read-back

Server A communicates with Server B only through approved private, authenticated interfaces.

Server A must not connect directly to the VICIdial database.

---

# 2. Server A Responsibilities

Server A owns:

- Odoo 19
- Codestra middleware
- PostgreSQL durable operational storage
- Redis short-lived real-time state
- Keycloak identity and service authentication
- n8n asynchronous workflows
- NATS JetStream durable event backbone
- Temporal durable business workflows
- AI Gateway
- AI provider abstraction
- AI prompt and model registries
- AI knowledge and retrieval
- AI review and evaluation
- Webhook Gateway
- outbound webhook delivery
- WebSocket Gateway
- agent desktop screen-pop orchestration
- appointment scheduling and reminder orchestration
- IVR policy, customer lookup, appointment lookup, and callback orchestration
- provisioning orchestration
- reporting and analytics
- deterministic metric library
- scoring models
- automation registry
- canonical event catalog
- rules engine
- SLA engine
- customer journey
- consent and preference center
- communication policy
- template management
- data-quality service
- feature-flag registry
- audit ledger
- release approval gates
- observability and distributed tracing
- object-storage integration
- secret-reference integration
- cross-server acceptance orchestration
- final evidence and go/no-go package

---

# 3. Responsibilities That Do Not Belong on Server A

Server A must not own or directly perform:

- Asterisk call routing
- VICIdial campaign execution
- predictive dialing
- live carrier control
- direct SIP endpoint configuration
- direct VICIdial database writes
- direct agent pause or resume without Server B confirmation
- direct callback publication into VICIdial
- direct endpoint registration in Asterisk
- raw live RTP handling through n8n
- raw live audio delivery through n8n
- unvalidated telephony state
- customer recording filesystem access
- telephony truth calculations that belong to VICIdial

Server A requests telephony actions through the Server B adapter and accepts success only after read-back.

---

# 4. Architecture Ownership

The accepted ownership model is:

- Odoo 19: business system of record
- VICIdial and Asterisk: telephony systems of record
- Middleware: secure real-time gateway
- PostgreSQL: durable operational truth for integration state
- Redis: short-lived real-time state
- Keycloak: user and service identity
- NATS JetStream: durable event transport
- Temporal: long-running business-critical workflows
- n8n: external integrations, asynchronous enrichment, notifications, and scheduled delivery
- AI Gateway: approved AI access and policy enforcement
- Webhook Gateway: secure external event ingress and outbound subscription delivery
- WebSocket Gateway: authenticated user-scoped real-time UI delivery

NATS must not replace PostgreSQL audit or idempotency.

Temporal must not replace n8n.

n8n must not enter real-time telephony, RTP, VAD, streaming transcription, TTS, call-control, transfer-execution, or screen-pop paths.

---

# 5. Full Engineering Authorization

Codex is authorized to:

- inspect Server A repositories, services, containers, databases, configurations, and evidence
- install compatible and pinned staging packages
- create private-only staging services
- create staging databases, schemas, namespaces, streams, consumers, and test fixtures
- implement or repair application code
- create and test staging migrations
- create and update Odoo 19 modules
- create and update middleware services
- create or reconcile NATS JetStream
- create or reconcile Temporal
- create or reconcile the AI Gateway
- create or reconcile the Webhook Gateway
- create or reconcile a separate n8n staging queue-mode deployment
- create or reconcile WebSocket delivery
- use fake providers and isolated message sinks
- run unit, contract, integration, security, load, recovery, and rollback tests
- restart only services within the authorized milestone
- correct defects and rerun tests
- create clean commits
- create backups after the baseline passes
- generate protected evidence and checksums
- continue autonomously through routine engineering decisions

Codex must stop only for:

- unavailable external credentials that cannot be generated locally
- unavailable official Odoo production migration service or entitlement
- unavailable DNS or provider ownership
- unavailable human UAT participants
- unavailable named approvers
- actions outside this authorization

---

# 6. Actions Not Authorized

Codex must not:

- enable production traffic
- activate production n8n workflows
- activate production NATS publishers
- activate production Temporal workflows
- expose public production webhook ingress
- send external email, SMS, or social messages
- process customer recordings or customer audio
- place or answer live calls
- activate public DIDs or carriers
- publish production leads to VICIdial
- provision production endpoints
- enable production IVR routing
- enable production callbacks
- enable production appointment auto-pause
- enable production WebSockets
- enable production transcription or AI
- perform historical VICIdial backfill
- perform Odoo production cutover
- perform an official production Odoo migration
- delete unreviewed repositories or customer data
- bypass formal release gates
- claim production readiness

---

# 7. Mandatory Safe State

The following must remain false or disabled:

- production traffic
- VICIdial writes
- lead publication
- campaign synchronization
- agent synchronization
- endpoint provisioning
- IVR routing
- IVR callbacks
- appointment auto-pause
- live WebSocket delivery
- live transcription
- real-time AI assistant
- post-call production AI
- production n8n delivery
- production exports
- public production webhook ingress
- production NATS publishing
- production Temporal workflows
- historical backfill
- external communications

Required final values:

- production flags true: zero
- active production n8n workflows: zero
- active production Temporal workflows: zero
- production NATS publishers: zero
- external messages sent: zero
- live calls processed: zero
- customer audio processed: zero
- customer recordings processed: zero
- production AI requests: zero
- public webhook connectors activated: zero
- production ready: no

---

# 8. Authoritative Specifications

Before implementation, Codex must verify the authoritative specifications and accepted evidence.

Required sources include:

1. Cross-Server Completion, Acceptance, and Production-Gate Plan
2. Missing Automation, AI API, and Webhook Architecture
3. Multi-business-unit hierarchy and access model
4. Middleware and n8n architecture
5. AI Services Layer
6. Appointment Reminder and Pre-Call Preparation System
7. Multi-Campaign IVR Design
8. Analytics, Reporting, Agent Scoring, and Campaign Performance System
9. Open-Source Call Transcription and Speech Analytics System
10. Ultra-Low-Latency Telephony and AI Architecture
11. Most recent accepted platform evidence and final reports

Codex must:

- confirm each file exists
- record each checksum
- identify the authoritative version
- reject competing drafts as authoritative
- preserve prior evidence
- stop fail-closed when a required source is unavailable or unauthenticated

Pasted text may be reference material, but it is not authoritative evidence unless its artifact and checksum are verified.

---

# 9. Exclusive Lock

Use:

`/root/codestra-production-completion/.locks`

The milestone lock must:

- reside on a persistent host-visible filesystem
- be a regular file
- not be a symbolic link
- use restrictive ownership and permissions
- use a kernel-level exclusive lock
- remain held by the same process for the entire milestone
- fail immediately when already held
- release automatically on process exit
- pass a two-process contention test

Do not use a read-only `/run/lock`.

Do not use `/tmp`.

Do not continue without a verified lock.

The kernel lock result is authoritative.

---

# 10. Baseline and Freeze

Complete the baseline before:

- backups
- package installation
- service creation
- repository changes
- configuration changes
- migrations
- restarts

Capture:

- execution and filesystem scope
- repositories, branches, commits, and dirty state
- services and containers
- images, versions, and digests
- public and private listeners
- Odoo version, modules, databases, scheduled actions, and workers
- middleware routes and deployed image
- PostgreSQL databases, schemas, roles, migrations, and extensions
- Redis topology, persistence, and exposure
- Keycloak realm, clients, roles, service accounts, sessions, and backup state
- n8n versions, deployments, credentials, workflows, and activation state
- NATS services, streams, consumers, subjects, accounts, and storage
- Temporal services, namespaces, workers, workflows, and storage
- AI services, providers, prompts, policies, and evaluation records
- webhook services, connectors, subscriptions, and public exposure
- WebSocket services and authentication
- reporting models and dashboards
- feature flags and kill switches
- object storage
- secrets management
- monitoring and tracing
- previous evidence and rollback material
- private connectivity to Server B
- read-only Server B adapter health

Failed commands must produce `UNKNOWN`, not a safe default.

Any unknown state affecting safety blocks implementation.

Do not collect unrestricted process command lines or secret values.

---

# 11. Requirements Traceability

Create a requirements traceability matrix.

Classifications:

- Implemented and tested
- Implemented but not tested
- Partially implemented
- Missing
- Conflicting implementation
- Obsolete implementation
- Blocked by external prerequisite
- Live acceptance required

Each item must include:

- requirement identifier
- source
- responsible service or repository
- current implementation
- current tests
- current evidence
- gap
- remediation
- final test
- final evidence
- remaining blocker

Do not infer completion from filenames, comments, inactive code, placeholder methods, or old reports.

---

# 12. Repository Consolidation

Inventory every relevant repository.

Record:

- name
- path
- branch
- commit
- dirty state
- owner
- purpose
- active or obsolete state
- production dependency
- secret scan
- test status

Produce one authoritative implementation for:

- contracts
- middleware
- Odoo modules
- NATS platform
- Temporal workflows
- AI Gateway
- Webhook Gateway
- WebSocket Gateway
- n8n workflows
- reporting and metrics
- observability
- cross-server tests

Rules:

- preserve current files
- do not delete unreviewed repositories
- archive only after review
- record provenance
- eliminate active duplicate schemas
- eliminate active conflicting migrations
- replace temporary scripts with maintained commands
- create one dependency and ownership map

---

# 13. Canonical Contracts and Event Catalog

Create or reconcile one canonical contract repository.

Include:

- OpenAPI contracts
- JSON Schemas
- canonical event envelopes
- error envelopes
- examples
- compatibility tests
- semantic-version history
- deprecation rules
- changelog

Domains:

- middleware
- Server B adapters
- telephony events
- reporting snapshots
- appointments
- IVR
- callbacks
- provisioning
- AI tasks and results
- WebSockets
- webhooks
- automations
- audit
- feature flags
- approvals

Every request and event includes:

- schema version
- request ID
- correlation ID
- idempotency key
- source service
- destination service
- environment
- business unit
- campaign where applicable
- timestamp
- data classification

Reject unknown major versions.

---

# 14. PostgreSQL Durable Foundation

Use one maintained migration chain.

Implement or reconcile:

- API requests
- durable idempotency
- inbox
- outbox
- delivery attempts
- dead letters
- event definitions
- automation definitions
- rule definitions
- AI tasks and results
- AI review cases
- webhook connectors
- webhook subscriptions
- webhook deliveries
- reporting snapshots
- metric snapshots
- appointment reminder events
- IVR sessions
- callback requests
- provisioning requests
- feature flags
- approval gates
- unified audit
- migration history
- Temporal business references
- reconciliation findings

Requirements:

- transactional writes
- request-hash conflicts
- append-only audit
- bounded retention
- verification queries
- rollback procedures
- staging migration tests
- rollback tests
- backup and restore evidence
- no production migration

No accepted event may be lost after a committed transaction.

---

# 15. NATS JetStream

NATS JetStream belongs on Server A.

First determine whether an accepted NATS deployment already exists.

Do not create a duplicate event backbone.

Required stream domains:

- telephony
- leads
- appointments
- transfers
- sales
- support
- retention
- AI
- provisioning
- audit

Required capabilities:

- private-only listeners
- pinned versions and images
- topology matching replica count
- persistent storage
- TLS or approved NKey/JWT security
- account isolation
- subject authorization
- business-unit and campaign headers
- schema validation
- publisher acknowledgment
- message IDs
- deduplication
- durable consumers
- work queues
- fan-out
- dead-letter subjects
- replay
- backpressure
- consumer monitoring
- backups
- restore tests
- OpenTelemetry propagation

Do not configure three replicas on one node.

Use one replica for a one-node staging deployment or a real private cluster.

Production publishers remain disabled.

---

# 16. Temporal

Temporal belongs on Server A.

First determine whether an accepted Temporal deployment already exists.

Do not create a competing workflow engine.

Required workflows:

- agent provisioning
- agent offboarding
- customer onboarding
- failed-payment recovery
- subscription renewal
- fulfillment
- compliance review
- lead nurture
- appointment lifecycle
- campaign activation

Each workflow requires:

- versioned inputs and outputs
- business-unit and campaign scope
- idempotent activities
- retry and non-retryable classifications
- compensation
- cancellation
- human approval signals
- deterministic timers
- search attributes
- audit
- feature flags
- simulation mode
- synthetic fixtures

Required platform controls:

- pinned supported versions
- private-only networking
- dedicated PostgreSQL schemas and roles
- staging namespaces
- worker isolation
- workflow versioning
- health and readiness
- metrics
- backup and restore
- controlled retention

Temporal does not replace n8n.

Production workflows remain disabled.

---

# 17. Automation Registry and State Machines

Create or reconcile an authoritative automation registry.

Each automation must declare:

- name
- technical code
- trigger event
- execution engine
- business-unit scope
- campaign scope
- workflow identifier
- workflow version
- input schema
- output schema
- allowed sources
- allowed destinations
- required permissions
- timeout
- retry policy
- dead-letter policy
- approval policy
- compensation workflow
- feature flag
- environment
- owner
- approver
- status

Execution engines:

- middleware
- Temporal
- n8n
- Odoo scheduled action
- AI service
- manual workflow

Approved status alone does not permit execution.

Execution requires:

- feature flag
- release gate
- environment match
- authorization
- scope validation
- schema validation
- idempotency
- audit

Create explicit state machines for:

- leads
- appointments
- AI tasks
- callbacks
- provisioning
- fulfillment
- retention
- compliance review
- webhook delivery

Every transition defines:

- allowed source states
- allowed target states
- authorized actor
- required data
- side effects
- events
- compensation
- audit

---

# 18. Deterministic Rules and Policies

Create or reconcile deterministic rules for:

- lead routing
- campaign eligibility
- hopper priority
- transfer eligibility
- appointment assignment
- callback assignment
- compliance requirements
- save-offer authority
- AI confidence thresholds
- escalation
- notification
- staffing alerts
- consent
- DNC and suppression
- quiet hours
- daily and weekly contact limits
- allowed channels
- country and jurisdiction rules
- calling windows
- export permissions
- recording permissions
- AI tool permissions

Rules support:

- versioning
- effective date
- expiration
- approval
- priority
- fixtures
- dry run
- preview
- audit

AI cannot override deterministic authorization, consent, compliance, campaign, payment, or customer-data rules.

---

# 19. AI Gateway

All AI access must pass through one Codestra AI Gateway.

The Gateway owns:

- caller authentication
- business-unit authorization
- campaign authorization
- AI task registry
- provider registry
- model registry
- prompt registry and versions
- structured output schemas
- approved action codes
- redaction
- output validation
- token and cost limits
- timeouts
- circuit breakers
- fallback
- durable PostgreSQL idempotency
- cancellation
- human review
- metrics
- audit

Supported task families:

- qualification
- call summary
- call audit
- sentiment
- objections
- next best action
- compliance review
- task status
- task cancellation
- task review
- provider health
- model listing
- campaign policy retrieval

Prohibited:

- provider keys in Odoo
- provider keys in browser code
- arbitrary prompts
- unrestricted model choice
- arbitrary Odoo writes
- executable instructions
- direct payment
- unrestricted refund
- customer deletion
- campaign changes
- permission changes
- unapproved transfer
- cross-unit reads

Use fake providers for staging when approved external credentials are unavailable.

---

# 20. AI Tool Broker, Knowledge, Evaluation, and Review

Create a controlled AI tool broker.

Allowed tools may include:

- retrieve approved customer summary
- retrieve approved product or service information
- retrieve campaign script
- retrieve support procedure
- check closer availability
- create draft appointment
- create draft support ticket
- recommend transfer
- retrieve order status
- retrieve project status

Every tool call passes through middleware authorization.

Create or reconcile the knowledge service.

Use the accepted vector platform when present.

Otherwise use PostgreSQL with pgvector for staging.

Filter all retrieval by:

- environment
- business unit
- campaign
- language
- product or service
- publication status
- effective date
- access level

Create an AI evaluation registry recording:

- task
- provider
- model
- prompt version
- dataset
- language
- business unit
- campaign
- precision
- recall
- accuracy
- false positives
- false negatives
- latency
- cost
- human-review rate
- limitations
- acceptance
- approver

Create a human-review queue for:

- qualification
- summary
- QA
- compliance
- sentiment
- objections
- forbidden phrases
- disclosures
- resolution
- churn risk

No model or prompt becomes production-eligible without accepted evaluation.

AI remains advisory.

---

# 21. Webhook Platform

Create or reconcile the Webhook Gateway.

Inbound flow:

- identify connector
- authenticate
- validate exact body
- validate timestamp
- reject replay
- validate payload size
- validate schema
- apply rate limit
- commit durable inbox
- acknowledge quickly
- publish canonical event
- process asynchronously
- audit

Supported authentication:

- HMAC
- JWT with issuer, audience, and key validation
- OAuth
- mTLS
- IP allowlists where appropriate

Required controls:

- connector-specific schema
- connector-specific rate
- idempotency
- secret rotation
- dead-letter
- replay console
- health
- safe errors
- no direct high-volume public Odoo webhook ingress

Outbound webhooks require:

- approved subscriptions
- field allowlists
- signed payloads
- subscription secrets
- exponential backoff
- jitter
- circuit breaker
- delivery history
- automatic disablement
- manual replay
- audit

Production public ingress remains disabled.

---

# 22. n8n Staging Queue Mode

Inventory the existing n8n deployment.

Do not modify or restart an unproven shared production deployment.

Create or reconcile a separate staging deployment with:

- pinned accepted n8n version
- main process
- webhook processors
- worker pool
- Redis
- PostgreSQL
- shared encryption key by secret reference
- queue-mode verification
- controlled concurrency
- execution-data pruning
- credential isolation
- private ingress
- staging service identity
- staging credentials
- inactive workflows

Every workflow declares:

- code
- version
- business unit
- campaign scope
- triggers
- outputs
- credential references
- owner
- SLA
- retry limit
- dead-letter behavior
- feature flag
- production approval state

Every workflow:

- validates envelope
- verifies source and authorization
- checks idempotency
- minimizes data
- performs external integration
- normalizes result
- returns through middleware
- handles retry
- handles permanent failure
- emits metrics
- creates audit

n8n does not calculate authoritative metrics independently.

n8n remains outside all real-time telephony paths.

All workflows finish inactive.

---

# 23. Missing n8n Workflows

Implement or reconcile:

1. Lead Ownership Expiration
2. Lead Recycling
3. Stale Opportunity Recovery
4. Duplicate Review
5. Consent Expiration
6. Suppression Synchronization
7. Agent Absence Reassignment
8. Appointment Conflict Resolution
9. Failed Transfer Recovery
10. Closer Capacity Alert
11. Support SLA Escalation
12. Fulfillment Exception Recovery
13. Contract Expiration
14. Incomplete Sale Recovery
15. Refund Approval
16. Chargeback Response
17. Customer Data Deletion
18. Customer Data Export
19. Credential Rotation Reminder
20. Connector Health Monitoring
21. Workflow Failure Digest
22. AI Cost Threshold Alert
23. Prompt Evaluation Reminder
24. Model Degradation Alert
25. Cross-System Reconciliation

Preserve and reconcile existing workflows for:

- reporting
- appointments
- IVR
- callbacks
- transcription
- AI
- provisioning
- retention
- notifications
- retry
- dead-letter

Deduplicate overlapping workflows through the automation registry.

---

# 24. CRM Automation

Implement or reconcile:

## Lead Ownership and Recycling

- ownership expiration
- maximum contact attempts
- cooling period
- supervisor review
- authorized reassignment
- lead-age priority
- contact-fatigue limits
- previous-owner attribution

## SLA Engine

Track:

- speed to lead
- appointment response
- transfer acceptance
- support response
- fulfillment acceptance
- complaint response
- retention response
- failed-payment response

Actions:

- warning
- supervisor alert
- reassignment
- priority increase
- manager escalation
- breach record

## Customer Journey

Link:

- lead
- calls
- appointments
- opportunity
- quotation
- sale
- fulfillment
- support
- retention
- upsell

Display:

- lifecycle stage
- owner
- last interaction
- blocker
- next action
- SLA
- sentiment
- revenue
- retention risk

## Consent and Preference Center

Track:

- phone consent
- email consent
- SMS consent
- social consent
- recording consent
- source
- version
- expiration
- opt-out
- DNC
- language
- preferred time
- preferred channel

Every automation checks preferences before contact.

## Communication Policy

Control:

- quiet hours
- daily contact limit
- weekly contact limit
- allowed channels
- country rules
- campaign rules
- retry timing
- templates
- opt-out
- delivery failure

## Template Management

Centralize:

- email
- SMS
- IVR prompts
- AI prompts
- call scripts
- objection responses
- appointment messages
- support messages
- retention offers

Every template has:

- version
- language
- campaign
- effective date
- approval
- compliance review
- publication state

## Data Quality

Monitor:

- invalid phone
- invalid email
- missing country
- missing timezone
- duplicate customers
- conflicting consent
- stale address
- incomplete campaign mapping
- missing owner
- orphan calls
- orphan recordings
- orphan appointments

## Simulation Mode

Support:

- dry run
- synthetic event
- no-write mode
- expected actions
- recipient preview
- target preview
- audit preview
- cost estimate
- side-effect list

---

# 25. Reporting, Analytics, and Scoring

Server A owns authoritative reporting calculations and dashboards.

Implement or reconcile:

- metric definitions
- targets
- results
- snapshots
- call scores
- lead scores
- agent scores
- team scores
- supervisor scores
- department scores
- campaign scores
- business-unit scores
- workforce intervals
- staffing forecasts
- performance alerts
- exports
- reconciliation
- score versions

Create a deterministic metric library outside dashboard code.

Required operational metrics include:

- call volume
- average speed of answer
- service level
- abandonment
- handle time
- occupancy
- speed to lead
- contact rate
- conversion
- revenue
- transfer performance
- appointment performance
- QA
- compliance
- retention
- upsell
- staffing

Requirements:

- formula version
- inputs
- exclusions
- null handling
- minimum sample
- unit
- rounding
- target direction
- fixtures

Dashboards:

- agent
- supervisor
- campaign
- business unit
- executive

Drill-down permissions must be revalidated server-side.

Exports require:

- permission
- scope validation
- field allowlist
- masking
- date and row limits
- watermark
- expiration
- audit
- business-unit isolation

Authoritative metric calculations remain outside n8n.

---

# 26. AI Transcription and Post-Call Review

Server A owns:

- transcription job orchestration
- transcript models
- redaction
- summary
- intent
- resolution
- sentiment
- objection
- QA
- compliance
- review cases
- evaluation
- recording-player authorization
- transcript search
- dashboards

Server A receives only approved recording or audio references from Server B.

Raw customer recordings remain unauthorized in this milestone.

Live transcription and AI voice remain inactive unless separately approved.

AI failure must not block telephony.

---

# 27. WebSocket and Real-Time Application State

Server A owns:

- Redis call state
- authenticated WebSocket Gateway
- user binding
- business-unit binding
- campaign binding
- event sequences
- reconnect
- replay of missing durable events
- cross-user isolation
- screen-pop delivery
- transcript delivery
- AI recommendations
- appointment reminders
- transfer summaries

Redis is not durable truth.

Every real-time event is also persisted through a durable channel where required.

The browser cannot subscribe to arbitrary users or campaigns.

---

# 28. Appointment Orchestration

Server A owns:

- appointment model
- reminder policy
- durable reminder records
- daily agent summary
- daily supervisor summary
- 15-minute popup
- 15-minute email to sink
- 5-minute preparation warning
- 2-minute APPT_PREP request
- due and overdue state
- supervisor escalation
- manager escalation
- conflict detection
- preparation workspace
- deliberate start action
- disposition
- KPI snapshots
- audit

Server A requests pause or resume from Server B.

Server A does not display pause or resume success until Server B read-back confirms it.

---

# 29. IVR and Callback Orchestration

Server A owns:

- DID policy
- business-unit policy
- campaign destination registry
- language policy
- menu definitions
- customer lookup
- appointment lookup
- campaign lock
- controlled reclassification
- callback business record
- callback SLA
- IVR session record
- screen-pop context
- audit
- reporting

Server B owns live dialplan and queue execution.

Server A never writes directly to the VICIdial database.

---

# 30. Identity and Provisioning Orchestration

Server A owns:

- Odoo employee approval
- Keycloak identity
- Odoo roles
- provisioning request
- one-time credential delivery token
- service authorization
- reconciliation
- offboarding orchestration

Server B owns:

- VICIdial user
- campaign permissions
- inbound groups
- Asterisk/WebRTC endpoint
- telephony read-back
- endpoint revocation

Server A must store only opaque secret references.

No credentials in email body, logs, source, or evidence.

---

# 31. Secrets and Object Storage

Use the accepted secrets-management mechanism.

Applications store references only.

Secrets include:

- provider keys
- SIP administrative credentials
- webhook signing secrets
- mTLS private keys
- database credentials
- email credentials
- SMS credentials
- n8n encryption key

Use approved S3-compatible object storage for:

- recording references
- transcripts
- exports
- evidence
- AI artifacts
- evaluation datasets

Requirements:

- private buckets
- short-lived signed references
- checksums
- retention
- legal hold
- access audit

Do not store large binaries directly in Odoo or middleware PostgreSQL.

---

# 32. Observability

Use OpenTelemetry across:

- Odoo
- middleware
- NATS
- Temporal
- n8n
- Server B adapter client
- AI Gateway
- Webhook Gateway
- WebSocket Gateway

Propagate:

- trace ID
- span ID
- request ID
- correlation ID
- event ID

Validate actual health and metrics endpoints.

Do not assume every service exposes `/metrics`.

Do not expose Prometheus, Grafana, tracing UI, collectors, Redis, PostgreSQL, NATS, or Temporal publicly.

Telemetry must not contain:

- raw transcripts
- phone numbers
- payment data
- credentials
- private keys
- unrestricted customer data

---

# 33. Security Tests

Run:

- valid mTLS
- expired mTLS
- revoked mTLS
- wrong service identity
- wrong environment
- wrong business unit
- wrong campaign
- JWT validation
- HMAC validation
- replay rejection
- idempotency conflict
- feature-flag bypass
- direct browser access
- cross-user WebSocket leakage
- cross-campaign leakage
- cross-business-unit leakage
- unauthorized export
- unauthorized recording access
- unauthorized transcript access
- webhook abuse
- NATS subject abuse
- Temporal signal/query authorization
- AI tool abuse
- SQL injection
- mass assignment
- path traversal
- SSRF where applicable
- secret scan
- log redaction

Critical and high findings must be fixed or remain blocking.

---

# 34. Reliability, Load, and Recovery Tests

Run:

- database migration and rollback
- inbox/outbox recovery
- duplicate request
- concurrent duplicate request
- out-of-order event
- sequence gap
- NATS publisher acknowledgment
- NATS consumer restart
- NATS replay
- NATS backpressure
- Temporal worker restart
- Temporal server restart
- Temporal timer persistence
- Temporal compensation
- n8n worker restart
- n8n queue backlog
- webhook replay
- webhook fast acknowledgment
- AI provider outage
- AI fallback
- Redis restart
- PostgreSQL restart
- Odoo restart
- WebSocket reconnect storm
- Server B unavailable
- object-storage failure
- secrets-manager failure
- backup and restore
- rollback

No accepted event loss.

No duplicate business side effects.

---

# 35. Cross-Server Synthetic Acceptance

After Server A and Server B implementation reports pass, Server A orchestrates synthetic acceptance.

Use only:

- synthetic customers
- synthetic agents
- synthetic DIDs
- synthetic queues
- inactive campaigns
- message sinks
- synthetic recording storage
- fake providers
- non-customer destinations

Test end to end:

## Reporting

Server B fixture to adapter to middleware to event backbone to Odoo to metric library to dashboard to report to reconciliation.

## Appointment

Appointment to reminder records to popup to email sink to APPT_PREP request to Server B read-back to deliberate start to disposition to resume.

## IVR and Callback

Synthetic DID to menu to campaign lock to queue to Odoo context to callback to Server B publication to read-back.

## Provisioning

Test employee to Keycloak to Odoo role to Server B user/groups/endpoint to one-time credential to read-back to offboarding and revocation.

## AI

Synthetic recording reference to transcript to redaction to summary to disclosure and forbidden-phrase detection to QA/compliance to review to dashboard to WebSocket recommendation.

## Automation

Canonical event to NATS to Temporal or n8n according to registry to result through middleware to Odoo.

## Webhook

Authenticated inbound event to durable inbox to NATS to authorized consumer and signed outbound delivery to sink.

## CRM

Lead expiration, recycling, SLA escalation, appointment conflict, failed transfer recovery, consent, communication limit, customer journey, and data-quality findings.

Unexplained synthetic reconciliation gaps must be zero.

---

# 36. Autonomous Defect Correction

Codex must correct defects autonomously.

After each correction:

1. Run focused tests.
2. Run affected integration tests.
3. Run security regression.
4. Run recovery regression.
5. Run the complete Server A acceptance suite before claiming PASS.

Do not claim PASS with:

- missing evidence
- unauthenticated specification
- missing checksum
- unknown safety state
- contradictory values
- placeholder behavior
- public internal listener
- duplicate stack
- duplicate side effect
- accepted event loss
- untested migration
- untested rollback
- active production workflow
- production flag true
- external message sent
- unresolved critical or high security finding

---

# 37. Final Safe State

At completion:

- all production feature flags false
- all n8n workflows inactive
- production Temporal workflows disabled
- production NATS publishers disabled
- public production webhook ingress disabled
- no external messages
- no live calls
- no customer audio
- no customer recordings processed
- no production AI
- synthetic credentials revoked
- staging services private
- evidence complete
- rollback complete

---

# 38. Required Final Report

Codex must report:

## Overall

- Server A implementation status
- requirements traced
- implemented and tested
- missing
- externally blocked
- conflicting implementations
- authoritative repositories

## Foundation

- contracts
- PostgreSQL
- migrations
- idempotency
- inbox/outbox
- audit
- feature flags
- approvals

## Platform Services

- NATS
- Temporal
- AI Gateway
- tool broker
- knowledge service
- webhook platform
- WebSocket
- n8n queue mode
- Keycloak
- secrets
- object storage
- observability

## Odoo Domains

- automation registry
- event catalog
- rules
- SLA
- journey
- consent
- communication policy
- templates
- data quality
- simulation
- reporting
- scores
- appointments
- IVR policy
- AI review
- provisioning orchestration

## Tests

- total tests
- failures
- security failures
- load failures
- recovery failures
- cross-unit leaks
- cross-campaign leaks
- duplicate side effects
- accepted event loss
- unexplained reconciliation gaps

## Invariance

- production flags true
- active production n8n workflows
- active production Temporal workflows
- production NATS publishers
- live calls
- customer audio
- customer recordings
- production AI requests
- external messages
- public webhook connectors
- production readiness

## Evidence

- evidence directory
- traceability matrix
- repository inventory
- contract report
- migration report
- NATS report
- Temporal report
- n8n report
- AI report
- webhook report
- security report
- performance report
- reconciliation report
- rollback report
- final report
- final checksum

The only acceptable production-readiness value for this scope is:

`PRODUCTION_READY=NO`

Production activation remains a separate formal authorization.

---

# 39. Paste-Ready Server A Mandate

Proceed autonomously with the full Server A implementation described in this document.

Treat the installed Server A environment as the baseline.

Do not deploy draft code or create duplicate application stacks.

Verify the authoritative specifications, evidence, lock, and safe state first.

Preserve passing components and implement only missing or deficient functionality.

Install only compatible, pinned, private-only staging dependencies that are genuinely needed.

Complete the canonical contracts, PostgreSQL durable foundation, NATS JetStream, Temporal, automation registry, rules engine, AI Gateway, tool broker, knowledge service, webhook platform, n8n queue mode, CRM automation, reporting, WebSockets, appointments, IVR policy, provisioning orchestration, Keycloak integration, secrets, object storage, observability, and release governance.

Use Server B only through approved private adapter interfaces.

Use synthetic records, fake providers, isolated message sinks, inactive workflows, and staging feature flags.

Do not activate production traffic, production workflows, public webhooks, production AI, customer media, live calls, production telephony, endpoint provisioning, or historical backfill.

Run the complete test program.

Correct defects autonomously and rerun all affected tests.

Do not accept unknown states, missing evidence, placeholder behavior, unsafe listeners, duplicate side effects, event loss, cross-unit leakage, cross-campaign leakage, or untested rollback.

Finish in the mandatory fail-closed state and return the complete evidence-backed final report.

Stop only for a verified external prerequisite or an action outside the authorization.
