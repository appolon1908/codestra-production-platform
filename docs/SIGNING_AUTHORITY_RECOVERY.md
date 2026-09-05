# Signing-authority recovery

## Status

Protected release `01f2676772b11919e1d79cc74d36bc5eeaa682cd` is
**non-activatable**. Server A has no independently recoverable trust anchor for
its signing key, and none of the host's candidate public keys verifies the
release manifest signature. Never install a scanned candidate as a substitute.

Email, SMS, and PSTN delivery must remain disabled throughout recovery.

## Separation of duties

The security owner generates a dedicated SSH Ed25519 keypair on an independent
protected workstation. The private key never exists on Server A. The owner
updates the protected GitHub Actions secrets
`CODESTRA_RELEASE_SIGNING_KEY` and `CODESTRA_RELEASE_SIGNING_PUBLIC_KEY`.

The normalized fingerprint is calculated independently over exactly
`<key-type> <base64-key-body>` without a comment or trailing newline:

```sh
awk '{printf "%s %s", $1, $2}' codestra-release.pub | sha256sum
```

The public key and its recorded 64-hex fingerprint travel to the Server A
security administrator through separate protected channels. Neither value is
accepted from the release bundle it authenticates.

## Successor release

1. Merge this recovery control through ordinary independent review.
2. Publish a new protected release from the resulting protected SHA.
3. Require GitHub Actions to sign and independently verify `manifest.sha256`
   with identity `codestra-release` and namespace `codestra-release`.
4. Confirm the release tag, manifest, checksum, provenance, SBOM and immutable
   workload digest all bind the new protected SHA.
5. Do not reuse, amend, or reactivate `protected-01f2676772b11919e1d79cc74d36bc5eeaa682cd`.

## Server A bootstrap

After publication, place only the approved public key at
`/secure-bootstrap/codestra-release.pub`. Provision the host trust anchor using
the independently recorded fingerprint:

```sh
sudo python3 tools/provision_release_trust_anchor.py \
  --public-key /secure-bootstrap/codestra-release.pub \
  --expected-sha256 '<independently-recorded-64-hex-fingerprint>' \
  --destination /etc/codestra/release/allowed_signers
```

Read back ownership, mode and normalized fingerprint without printing key
material. Verify the new release signature before extraction.

## Exposed runtime-authority rotation

`config/environment-secret-rotation-ownership.json` is the ownership contract
for `ODOO_OUTBOUND_HMAC_SECRET` and `KLYROW_WEBHOOK_SECRET`. They form one
atomic group because both currently reside in the same root-owned environment
file. A partial field update is prohibited.

Success requires staged successor authorities at both ends, delivery switches
remaining false, an atomic environment-file replacement, narrowly scoped
consumer recreation, health read-back, new-key acceptance, predecessor
revocation, and old-key rejection. Any failure restores the entire prior file
and verifier set before consumer recreation. Secret values, hashes suitable for
offline guessing, environment dumps, and rollback material never enter logs or
repository evidence.

Runtime rotation remains blocked until the protected implementation providing
the named acceptance/rejection validators is published and installed. The
ownership contract alone is not authorization to mutate Server A.
