# Signing-authority recovery and exposed runtime-secret rotation

## Incident disposition

Protected release `01f2676772b11919e1d79cc74d36bc5eeaa682cd` is **NON-ACTIVATABLE**:
its signer trust anchor cannot be independently recovered. The GitHub release
notice is an incident annotation, not a cryptographic revocation. The proposed
validator, operator, and installer reject this SHA; already installed historical
code does not acquire those checks until an approved installation. Keep its
activation authorization withheld. Do not re-sign or reuse its release assets,
install scanned candidate keys, or weaken signature/provenance checks.

The protected `Quarantined release recovery` workflow is the only remote
recovery dispatch. It executes the current protected workflow revision, loads
the fixed quarantined tuple from `config/signing-authority-rotation.json`, and
accepts only `status`, `collect-evidence`, `disable-production-web-traffic`, or
`disable-klyrow-email-delivery`. It has no tuple, ref, or command input and
cannot stage, deploy, activate, send a canary, or obtain a registry deployment
token.

`config/signing-authority-rotation.json` is the incident record. Pending fields are
not evidence of completion. Email, SMS, PSTN and canary delivery remain disabled
through this procedure. No customer message, SMTP DATA, SIP registration, or call
is permitted. An independent reviewer must approve the final PR head even if
GitHub's current branch policy requires zero approving reviews.

## Dedicated signing authority: independent protected workstation only

The security owner generates a dedicated SSH Ed25519 release keypair on an
independent protected workstation. Never run this step on Server A, reuse an
operator/host/deployment key, or transfer the private key to Server A. Use the
organization's protected key-generation and backup procedure. Restrict the private
key to the protected release workflow and its authorized custodians.

From that workstation the owner stores the private key as the protected GitHub
Actions secret `CODESTRA_RELEASE_SIGNING_KEY` and its public key as
`CODESTRA_RELEASE_SIGNING_PUBLIC_KEY`. Confirm the secret scope matches the release
job, and that the protected branch/workflow and secret administration permissions
prevent an unreviewed workflow from obtaining the key. Record secret update audit
IDs and scope, never secret values. Do not grant broader access to work around a
scope mismatch.

Independently calculate and retain the normalized fingerprint:

```sh
awk '{printf "%s %s", $1, $2}' codestra-release.pub | sha256sum
```

Require exactly one valid SSH Ed25519 public key line. The expected result is
64 lowercase hexadecimal characters hashing `key-type SPACE key-blob` with no
trailing newline or comment. It is not the `SHA256:...` output of `ssh-keygen -lf`.
Send only the public key and the independently recorded fingerprint to the Server A
security administrator through separate protected channels. Record the two channel
receipt IDs, owner identity, timestamp, and independent verification attestation.
Do not derive the expected fingerprint from the received key on Server A.

## Protected repository and new publication

1. Validate this contract and run the complete source/required CI checks. Open a PR
   against `release/production-activation`. Obtain independent approval of the exact
   final head, record reviewer/head/time, and merge normally without bypass.
2. Before merge (which triggers publication), require security-owner evidence that
   both new signing secrets are installed. Do not publish with the previous secrets.
3. Publish a completely new `protected-<new SHA>` release from the protected merged
   SHA. Do not change or replace old signed assets or reuse the blocked SHA.
4. Require successful Actions evidence for signing `manifest.sha256` with namespace
   `codestra-release`, then verifying with identity `codestra-release`, namespace
   `codestra-release`, and the separately supplied public-key secret. Verification
   must not derive its trusted public key from the private signing key. The current
   workflow performs these separate commands; a source review is not a successful
   run attestation. Capture the new URL, exact SHA, run ID/attempt and checks.

## Server A trust bootstrap and release verification

Only after publication, the security administrator places the newly received public
key at `/secure-bootstrap/codestra-release.pub`, root-owned and not writable by
untrusted users. The signing private key never reaches Server A. From the reviewed
new source, run the following with the fingerprint from the independent channel:

```sh
python3 tools/provision_release_trust_anchor.py \
  --public-key /secure-bootstrap/codestra-release.pub \
  --expected-sha256 "$INDEPENDENT_NORMALIZED_FINGERPRINT" \
  --destination /etc/codestra/release/allowed_signers
```

Run as the security administrator with root permissions. Read back owner, mode,
identity and normalized fingerprint. The provisioner rejects a different installed
anchor; stop and resolve an unexpected anchor through a separately recorded owner
procedure rather than deleting it automatically.

Download the new release into isolated storage and verify its manifest signature
with the installed anchor, identity and namespace above **before trusting the
manifest or executing its code**. Require safe asset names, checksums, deployment
manifest binding to the exact protected merged SHA, SBOM and provenance checks,
canonical middleware source SHA, immutable image digest, image revision label,
and migration revision. Preserve run/artifact IDs and verification exit status.
Missing, mismatched, unsigned or expired evidence blocks progress.

## Ownership and atomic consumer rollout

`config/runtime-secret-rotation-ownership.json` is a separate ownership manifest
for environment entries and cross-service consumers. It must not be fed to
`scripts/rotate_service_secrets.py`: that TSV runner rotates whole files per service
and restores old values on failure. It cannot atomically rotate these environment,
database, alias and remote-provider consumers. Do not replace the complete shared
environment file with one secret value.

The manifest's numeric owners are required source-backed policy, not observed live
metadata. Before any mutation, the Server A administrator and named peer owners
must inventory **every** active replica, paused replica, scheduled job, alias,
secret-file override and remote signer/verifier. Record actual UID/GID, mode,
read access, mount mode where applicable, storage location, restart mechanism,
and immutable image revision. Block on missing consumers or unapproved differences.
Environment entries have no container file path; do not invent a `/run/secrets`
mount. Review access to process environments and Docker metadata as secret access.

- `ODOO_OUTBOUND_HMAC_SECRET`: control-plane worker event signer, API CRM signer,
  `CRM_ODOO_HMAC_SECRET` override, and the deployed Odoo endpoint verifier. The
  configuration script writes `codestra.webhook_secret`; confirm the actual deployed
  verifier/configuration before proceeding, including CRM/email-event routes.
- `KLYROW_WEBHOOK_SECRET`: control-plane API verifier, private integration gateway
  signer/verifier, Klyrow publisher, and `codestra-email-reseller-api-1` verifier.
  The email-reseller has a separate environment authority at
  `/etc/codestra/secrets/kyqra-telnexa/middleware.env`; recreate only its `api`
  service through `deploy/email-reseller/compose.yaml` and require a paired
  synthetic new-secret acceptance plus explicit predecessor-authentication denial.
  Rotation cannot pass while this verifier accepts the predecessor. Inspect
  `KLYROW_WEBHOOK_SECRET_FILE` first
  where supported because it overrides the environment. The gateway's default
  environment file is `/etc/kyqra-telnexa-integration/shared.env`; the remote owner
  must attest the actual deployment/storage. No remote mutation is authorized by
  merely filling the local manifest.

Treat both secrets and all their consumers as one maintenance transaction:

1. Acquire an exclusive rotation lock and record a unique change/rotation ID.
   Require the approved new release, owner roster, backups and tested recovery plan.
   Verify delivery kill switches and transport denial; do not print environment
   values. Pause publishers, ingress, workers, schedulers and queued retries on
   every peer; drain in-flight work and record zero active processing.
2. Stage two distinct, cryptographically random replacement runtime secrets using
   approved secret storage. Do not use the release-signing key. Hold the old values
   only in protected short-lived validation storage. No values in CLI arguments,
   shell tracing, logs, Git, evidence, or hashes of runtime secrets.
3. With all consumers stopped, atomically replace each complete environment file
   on its own filesystem using a mode-0600 temporary file, fsync and rename while
   preserving unrelated entries. Update approved Odoo configuration transactionally
   and coordinate the remote provider/gateway owner changes. Read back equality
   in-process without printing values. Reconcile every alias/file override.
4. Recreate all affected processes/replicas to clear cached environments and key
   material. Start them in isolated validation mode with production egress denied.
   A set of filesystem renames is not a distributed atomic transaction: the
   quiescence barrier stays closed until every consumer validates one new epoch.
5. For each actual signer/verifier route, issue harmless synthetic authentication
   probes with fresh timestamps and distinct event/nonce/idempotency IDs. Prove
   the new secret authenticates and the old secret receives an explicit signature
   authentication denial. A timeout, connection failure, missing executable, 404,
   replay rejection, rate limit, or generic 5xx is **inconclusive**, never PASS.
   Prove ordinary credentials/routing remain valid with a paired new-secret probe.
   Validate every replica, including overrides. Keep requests in an isolated
   non-delivering test route/tenant; do not enqueue customer work.
6. Validate restart health, secret readability, owner/mode read-back, old-key
   rejection and production delivery denial. Independent owners sign off the
   complete consumer matrix. Destroy protected old-secret probe material according
   to the incident retention policy after evidence review. Keep processing paused
   until the remaining preflight gates pass; no canary authorization is implied.

## Rollback and audit

Any partial rollout or failed/inconclusive probe leaves the barrier closed and
production delivery disabled. Restore compatible software/data to a known disabled
state, preserving audit and queued-event idempotency. **Never restore exposed
secrets as accepted credentials.** If replacement values cannot be used safely,
issue a fresh replacement epoch and repeat the coordinated rotation. Rollback may
end in a stopped service; availability does not override rejection of exposed keys.
Test this recovery in an isolated environment before production mutation.

Evidence contains only change/rotation IDs, owner/reviewer identities, UTC times,
consumer names, image digests, numeric file metadata, public signing fingerprint,
GitHub run/release references, probe correlation IDs, classified auth results,
kill-switch states and PASS/FAIL/BLOCKED per gate. Exclude request bodies, auth
headers, signatures, private keys and runtime secrets. Store restricted evidence
atomically and record its checksum and audit location. Do not report contract tests
or synthetic-key tests as proof of live rotation.

## Resume sequence

After trust and runtime rotation evidence pass, resume in order: backup; backup
validation; isolated restore/rollback validation; exact approved operator installation;
resolver repair with read-back; migration verification; SMTP no-DATA testing;
relay-denial testing; protected preflight. Any failure leaves production email,
SMS and PSTN disabled. A canary requires every gate to pass and explicit separate
authorization naming one internal recipient. This mission supplies no recipient
and authorizes no canary or production delivery.
