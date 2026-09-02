# Codestra Orbit V2 production adoption authority

This directory registers `appolon1908-hue/codestra-production-platform` as the
**deployment, evidence, and rollback authority** for Codestra Orbit V2. It is
not a second UI source repository.

## Source ownership

The shared `@corporate/*` packages, design tokens, authentication shell,
header, four footer variants, eight supported social networks, governed
content client, and page rules are owned by
`appolon1908-hue/SDK-repository`.

The current review candidate is SDK pull request 75. Its pull-request head is
recorded only as review evidence. It is not an installable production release.
This repository may pin packages only after that change is accepted into its
protected branch and a post-merge release publishes fresh artifacts tied to
the accepted source SHA.

Committed superseded archives from the SDK review candidate are never
installable. Consumer applications must use the final protected artifacts and
their recorded SHA-256 values.

## Repository role

This repository records:

- the exact protected Orbit source release;
- package names, versions, and artifact digests;
- every adopting repository and protected pull request;
- canonical domains and ownership;
- identity clients and redirect allowlists;
- immutable consumer application artifacts;
- Caddy and Kong source locks;
- desktop and mobile staging evidence;
- accessibility and authentication/session certification;
- observability and rollback evidence;
- the separate production deployment gate;
- exact production readback.

No shared UI implementation, copied package source, generated archive, brand
asset, secret, customer data, or runtime dump belongs here.

## Current state

`PREPARED_PENDING_SDK_PROTECTED_RELEASE`

The current contract is intentionally fail closed:

```text
PRODUCTION_READY=FALSE
RUNTIME_ACTIVATED=FALSE
PACKAGE_INSTALL_ALLOWED=FALSE
OVERALL_RUNTIME_GATE=BLOCKED
```

A branch or pull-request name does not change this state. Promotion requires
the machine-readable manifest, consumer ledger, and runtime gate document to
agree and pass validation.

## Validation

Run:

```bash
python tools/validate_orbit_adoption.py
python -m pytest -q tests/test_orbit_adoption.py
```

The validator rejects:

- a target other than `release/production-activation`;
- a competing Orbit UI/package implementation in this repository;
- a pending SDK candidate marked installable;
- production readiness without exact protected source and package digests;
- incomplete consumer, domain, identity, edge, staging, accessibility,
  session, observability, rollback, deployment-gate, or readback evidence;
- an activation claim while any runtime gate is not `PASS`.

## Safety

This adoption contract changes source governance only. It does not modify
servers, DNS, TLS, Caddy or Kong runtime state, identity-provider clients,
secrets, containers, databases, provider capabilities, or live traffic.
Production activation is a separate protected change.
