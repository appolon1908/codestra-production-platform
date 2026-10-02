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
whose values schema consists of the nine approved boolean fields. Each view
also carries a bounded UTC generation timestamp and exact image/revision
bindings for the three fixed services. All views must be fresh, mutually
consistent, and match fresh fixed-field Docker inspection before PASS. A
fixed template projects only the nine approved booleans from each live
container, so same-image container recreation or runtime flag drift cannot be
masked by stale readback files and no unrelated environment value is emitted.
Release identity is recursively validated and projected to an exact
immutable-release schema for the four fixed containers. Nested or extra fields
are rejected. This avoids reading or materializing complete container
environments.

Release identity read-back is valid for at most five minutes and is compared
with fresh fixed-field Docker inspection for every approved container. The
running digest-qualified image reference and OCI source/revision labels must
match the asserted release before PASS. Each asserted source commit must equal
its OCI source revision, and both values are bound to that live label.

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

Negative authorization and callback probes also remain incomplete (nonzero)
until separately reviewed positive synthetic-identity and signing authorities
exist. The invalid-signature callback case uses a current in-window timestamp
and a format-valid, non-matching SHA-256 signature so timestamp expiry or
header-format rejection cannot mask missing cryptographic enforcement.

The no-effect capability readback is recursively projected before any value is
emitted. Its adapter name and SHA-256 use fixed scalar formats, its authority
flags are strict booleans, and its UTC expiry must be valid and unexpired.

## Build and release

`build-operator-artifact.py` creates a deterministic archive, installation
manifest, SPDX SBOM, SLSA-shaped provenance statement, and checksum manifest.
Every workflow invokes the artifact builder itself with Python isolated mode;
every build then invokes the exactly pinned Bandit source scanner over the complete
Python operator/build surface and derives the vulnerability report and PASS
gate from the actual result; the report retains all high, medium, and low
counts. The protected-branch workflow runs the tests and dependency and source
vulnerability gates, builds at the exact merge SHA, signs
`SHA256SUMS` with the Codestra release signing identity, verifies that
signature, and publishes an immutable SHA-addressed GitHub release.
Publication is retry-safe: it creates a draft, accepts only the exact target
commit and fixed asset set, compares already uploaded assets byte for byte,
uploads only missing assets, re-verifies the complete set, and publishes only
after the assets are complete; the final gate proves the published tag resolves
to the protected source SHA.

Unsigned local bundles are development evidence only and are rejected by the
installer.

## Installation boundary

The installer requires all of the following:

- a checksum-matching SHA-addressed archive;
- a valid SSH signature over `SHA256SUMS` in the
  `codestra-klyrow-validator` namespace;
- the approved release signer identity;
- checksum-bound installation manifest, SPDX SBOM, SLSA provenance, and
  passing vulnerability report whose source and artifact identities agree;
- one Ed25519 operator public key;
- an explicit source CIDR, expiry, approver, and change ID.

Before verification, every release input and the operator public key are read
once through a no-follow descriptor into a private mode-0700 staging directory.
The installer verifies, extracts, copies, and records digests only from that
mode-0600 snapshot, so changes to owner-writable handoff paths cannot replace
evidence or signer authority between verification and installation.
Archive extraction does not depend on the version-specific `tarfile` data
filter. After validating the complete fixed member set, it creates each regular
payload file exclusively through a no-follow directory descriptor, enforces the
per-file and total size bounds while copying, and syncs the private extraction
directory before installation.

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

The signed release evidence and allowed public signer are copied read-only
into the immutable version directory. Host validation rechecks their digests,
source/artifact binding, and detached signature without contacting application
services.

An exact retry of a successfully installed source SHA is idempotent only when
the root-owned installation record, requested authority inputs, immutable
version, stable entrypoints, forced key, sudo boundary, and signed release
evidence all revalidate. Drift or a different artifact fails closed.

The installer records a private rollback set before changing operator files.
`remove-klyrow-production-validator.py` restores those exact files and removes
only the selected immutable version. `revoke-klyrow-validator-key.py` removes
exactly one forced-command entry matching an expected fingerprint and leaves
unrelated keys untouched. None of these programs invoke Docker, Compose, or an
application service manager.

Rollback never restores a whole stale `authorized_keys` snapshot. It removes
only the matching validator entry (or accepts that the separately tested
revocation already removed it) and preserves unrelated key additions or
rotations; an unexpected validator entry fails closed.
All backup records, checksums, target types, the validator key plan, and the
immutable version path are preflighted before the first rollback mutation.
Revocation and rollback write replacement key files only through randomized,
exclusive, no-follow descriptors and verify the opened inode before the atomic
rename; deterministic attacker-created temporary symlinks are never opened.

The `--simulator-root` option is accepted only for a root under
`/tmp/kpv-simulator-*` containing `.kpv-disposable-simulator`. It exists solely
for CI integration tests and cannot redirect a production operator action.

## Audit and output safety

Every privileged action is serialized by a nonblocking lock. The root helper
writes bounded, redacted JSON audit records under the root-owned validator
state directory and evidence records under its fixed evidence root. Each
evidence record includes the bounded structured authoritative read-back and
its digest; audit records retain the digest and size. The forced-command
dispatcher emits a correlated journal record that includes the installed key
fingerprint and SSH source address. Output has per-action time and size limits;
secret-shaped fields, bearer values, and private-key blocks are redacted.
Evidence is created before a PASS audit row is appended, so the audit log cannot
claim a successful action whose required evidence record is absent.

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
