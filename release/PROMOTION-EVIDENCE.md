# Release-instance evidence gate

The JSON Schema checks shape, canonical workload coverage and source names. It
cannot establish independence of staging and production artifacts or verify
the referenced bytes. Release-instance acceptance therefore requires both:

```sh
python scripts/validate_platform_authority.py \
  --manifest /approved/candidate.json --evidence-root /approved/bundle
```

The equivalent standalone artifact check is:

```sh
python scripts/validate_platform_release_evidence.py /approved/candidate.json \
  --evidence-root /approved/bundle
```

The commands read files only. They neither contact a runtime nor authorize
installation, traffic, migrations, provider delivery or production activation.
An accepted input is not proof of authenticity: signature/trust-root checks,
independent approvals, current runtime observations and existing release gates
remain mandatory outside this offline consistency check.

Every referenced contract, composition and edge file must match its exact
SHA-256. All promotion artifacts must be listed in the manifest evidence index,
be bounded regular files under the chosen root, and be distinct by both path and
SHA-256 across environments and evidence classes. Symlinked paths, duplicate JSON
keys, empty artifacts, substituted bytes and unbound index entries fail closed.

Promotion evidence is JSON with these mandatory subject fields:

```json
{
  "schema_version": "platform-promotion-evidence.v1",
  "environment": "staging",
  "evidence_class": "integration",
  "release_id": "the-exact-candidate-release-id",
  "authority_git_sha": "the-exact-candidate-source-sha",
  "service_digests": {"every-release-service-id": "its-exact-image-digest"},
  "result": "PASS"
}
```

The example is explanatory, not usable evidence. Actual `service_digests` must
contain the complete manifest service-to-image mapping. Accepted staging needs
integration, backup, restore, monitoring and rollback artifacts; production
also needs its independent approval artifact. Renaming/copying a staging file
or editing only the manifest environment label cannot satisfy production.
Tests use explicitly synthetic evidence and establish no deployed-system PASS.
