# Klyrow production validator

This directory is the canonical source for the `codestra-admin` bounded
production-validation operator. It is intentionally separate from the Server A
activation operator: that operator is root-oriented and exposes mutation
actions that are outside this contract.

The validator is default-deny. The SSH-facing executable accepts exactly one
of the action names in `command-contract.json`; `ssh-dispatch` accepts
`SSH_ORIGINAL_COMMAND` only when it exactly matches
`klyrow-production-validator <approved-action>`. No parsed command is passed to
a shell. The root helper is reachable through exact sudoers command lines and
executes a fixed action runner with a fixed action name.

The contract contains no deployment, restart, shell, generic Docker, send, or
canary action. Emergency stop remains a separate authority and is not exposed
by this operator.

## Read-only data contract

Inventory and health use fixed argv vectors and fixed container names. Docker
inventory is filtered separately to each approved container, and listener
inventory is limited to the fixed application and SMTP ports in the contract;
neither action enumerates unrelated host workloads. Container health passes
only when every fixed container explicitly reports `healthy`. The
configuration action reads only three root-owned, non-symlink JSON readbacks
whose schema consists of the nine approved boolean fields. Release identity is
recursively validated and projected to an exact immutable-release schema for
the four fixed containers. Nested or extra fields are rejected. This avoids
reading or materializing complete container environments.

Authorization, no-effect, callback, and SMTP no-DATA actions require reviewed
companion probes under
`/opt/codestra/operators/klyrow-production-validator/probes`. Every probe is
selected by a fixed action name, must be a root-owned regular file, and must
match the digest in the root-owned `probe-manifest.json`. A missing manifest,
missing probe, or digest mismatch fails closed. The pre-existing
`tests/production_safe_smoke.py` in Klyrow is not used because it performs
database writes and therefore is not production-safe for this contract.

The protected artifact includes the probe core and all four fixed entrypoints.
Negative authorization and rejected-callback probes use only deliberately
invalid identities. The SMTP probe issues EHLO, STARTTLS, MAIL, RCPT, and QUIT
but has no DATA operation. The no-effect probe intentionally returns blocked
until a separately reviewed synthetic-identity adapter authority is present;
it never substitutes the unsafe smoke script or guesses credentials. Operator
`READY` certifies the command boundary and installed probe digests, not the
outcome of later application tests.

The no-effect capability readback is recursively projected before any value is
emitted. Its adapter name and SHA-256 use fixed scalar formats, its authority
flags are strict booleans, and its UTC expiry must be valid and unexpired.

## Build and release

`build-operator-artifact.py` creates a deterministic archive, installation
manifest, SPDX SBOM, SLSA-shaped provenance statement, zero-dependency
vulnerability report, and checksum manifest. The protected-branch workflow
runs the tests and vulnerability gate, builds at the exact merge SHA, signs
`SHA256SUMS` with the Codestra release signing identity, verifies that
signature, and publishes an immutable SHA-addressed GitHub release.

Unsigned local bundles are development evidence only and are rejected by the
installer.

## Installation boundary

The installer requires all of the following:

- a checksum-matching SHA-addressed archive;
- a valid SSH signature over `SHA256SUMS` in the
  `codestra-klyrow-validator` namespace;
- the approved release signer identity;
- one Ed25519 operator public key;
- an explicit source CIDR, expiry, approver, and change ID.

It installs a root-owned version directory under
`/opt/codestra/operators/klyrow-production-validator/<source-sha>/`, verifies
stable entrypoint copies, installs exact sudoers entries, and replaces only a
matching unrestricted occurrence of the approved key with a forced-command
entry. The key entry enforces source restriction, expiry, `restrict`, no agent
or port forwarding, no X11 forwarding, no PTY, and no user rc.

Post-install validation parses the forced-key entry as one exact grammar and
binds its Ed25519 fingerprint, source restriction, expiry, full option set, and
complete `authorized_keys` checksum back to the root-owned installation and
operator-identity records. Drift fails closed.

The installer records a private rollback set before changing operator files.
`remove-klyrow-production-validator.py` restores those exact files and removes
only the selected immutable version. `revoke-klyrow-validator-key.py` removes
exactly one forced-command entry matching an expected fingerprint and leaves
unrelated keys untouched. None of these programs invoke Docker, Compose, or an
application service manager.

The `--simulator-root` option is accepted only for a root under
`/tmp/kpv-simulator-*` containing `.kpv-disposable-simulator`. It exists solely
for CI integration tests and cannot redirect a production operator action.

## Audit and output safety

Every privileged action is serialized by a nonblocking lock. The root helper
writes bounded, redacted JSON audit and evidence records. The forced-command
dispatcher emits a correlated journal record that includes the installed key
fingerprint and SSH source address. Output has per-action time and size limits;
secret-shaped fields, bearer values, and private-key blocks are redacted.

## Administrative procedure

1. Merge through the protected `release/production-activation` branch with an
   independent approval and passing exact-head checks.
2. Download the exact-SHA release and verify its checksum and signature from an
   independently sourced allowed-signers file.
3. Invoke the installer as the bounded installation administrator, never from
   the validator SSH key.
4. Run `validate-klyrow-production-validator.py` for the exact source SHA.
5. Test the exact approved key with `status`, `authenticate-runbook`, negative
   commands, forwarding denial, and PTY denial. Do not run inventory in the
   operator-authentication mission.
6. Revoke with the exact key fingerprint. Roll back with the exact source SHA.

Application validation may resume only after the installed host boundary,
audit trail, revocation, and rollback tests pass.
