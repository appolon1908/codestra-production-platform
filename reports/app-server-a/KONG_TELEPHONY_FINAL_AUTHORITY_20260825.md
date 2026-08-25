# Kong and telephony final authority — 2026-08-25

The production maintenance gate remained active. Caddy was not changed and no
call was placed.

## Server B authority

```text
SERVER_B_OPERATOR_REPOSITORY=https://github.com/appolon1908-hue/codestra-production-platform.git
SERVER_B_OPERATOR_BRANCH=agent/control-plane-release-consolidation-20260822
SERVER_B_OPERATOR_COMMIT=e95fcb1940d2a2a2b79392dfbb695ea55128f201
SERVER_B_SUDOERS_SOURCE=operations/vicidial-operator/codestra-vicidial-safety-status.sudoers
DEPLOYMENT_METHOD=approved Server B root console runs staged root-only installer
```

The live operator had no tracked source authority. A reviewable compatibility
wrapper now preserves it as an immutable legacy core and adds only
`telephony-safety-status`. The action runs five exact Asterisk readbacks without
a shell and emits seven allowlisted sanitized fields. Direct Asterisk sudo and
unsupported actions remain denied. The installer backs up the live operator and
sudoers, validates Python and sudoers, uses atomic installation, and validates
the action after installation.

The package is staged at
`/home/codestra-admin/codestra-vicidial-safety-status-e95fcb1` on Server B.
All three staged file hashes match the committed local files. The current
restricted account cannot install the package; the documented root-console
bootstrap is required.

## Middleware VICIdial path

The authoritative middleware repository change is commit
`454a5e06c0d0c2d3bc88132f928ecd4122aefb34` on branch
`agent/vicidial-private-dns-20260825`. The three production services now have:

- exact hostname mapping `edge.internal.codestra.agency:10.40.0.2`;
- the existing `codestra_edge` private network in addition to the backend;
- the existing production VICIdial mTLS bundle mounted read-only.

All three live services were recreated without dependencies and are healthy.
From each actual container:

```text
DNS=PASS (10.40.0.2)
TCP=PASS (8443)
TLS=PASS (TLSv1.3, verified SNI/CA)
MTLS=PASS
NO_CLIENT_CERT=REJECTED
READ_ONLY_HEALTH=HTTP_200
READ_ONLY_READY=HTTP_200 writes_enabled=false
CLIENT_CERT_NOT_AFTER=2026-11-15T02:54:50Z
```

No public listener, staging address, random alias, or security switch was
introduced.

## Current gate

The Server B package is not installed because no available approved command can
cross the existing root boundary. Therefore the official Server A operator
still cannot obtain authoritative Asterisk counts, and it remains unsafe to
change the Kong gate.

```text
TELEPHONY_PROBE=FAIL_PENDING_PRIVILEGED_INSTALL
ACTIVE_CALLS=UNKNOWN
ACTIVE_CHANNELS=UNKNOWN
SIP_REGISTRATIONS=UNKNOWN
TELEPHONY_ACTIVITY_SAFE=NO
OPERATOR_ACTIVATION_SAFE=NO
MAINTENANCE_GATE_CHANGE_APPROVED=NO
CADDY_KONG_MIDDLEWARE_CANARY=BLOCKED
```

## Tests

```text
PLATFORM_TESTS=104_PASS
MIDDLEWARE_TARGETED_TESTS=21_PASS
OPERATOR_SECURITY_TESTS=PASS
SUDOERS_SYNTAX=PASS
ARBITRARY_ASTERISK_COMMAND=DENIED
APPROVED_OPERATOR_ACTION=PENDING_ROOT_INSTALL
UNEXPECTED_KONG_DRIFT=0
KONG_CALLBACK_ROUTES=PASS
MIDDLEWARE_VICIDIAL_DNS=PASS
MIDDLEWARE_VICIDIAL_TCP=PASS
MIDDLEWARE_VICIDIAL_TLS=PASS
MIDDLEWARE_VICIDIAL_MTLS=PASS
```

## Required external action

An authorized Server B root-console operator must review and execute:

`/home/codestra-admin/codestra-vicidial-safety-status-e95fcb1/install-vicidial-safety-status.sh`

After that, deploy the committed Server A consumer update using its established
root installer, run official safety status, and proceed only if calls and
channels are both zero. This is a privilege-boundary deployment requirement,
not authorization to activate production traffic.

