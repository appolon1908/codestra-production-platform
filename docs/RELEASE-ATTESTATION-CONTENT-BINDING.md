# Release attestation content binding

## Source remediation, 2026-09-07

Related production trackers: #227, #234, #239 and #262. This change hardens
content validation only; it does not close their runtime acceptance criteria.

The existing generic predicate verifier accepted a copied JSON `null` when the
verified statement had no predicate, treated nested JSON `true` as equal to
numeric `1`, and returned on a matching record before validating later records.
The signed release consumer used the same Python dictionary equality for SPDX
content, so its boolean/number comparison also needed correction.

The shared verifier now rejects absent, empty or incorrectly typed predicates;
invalid or missing base64 payloads; malformed or empty verification documents;
duplicate JSON object keys; and non-finite JSON numbers. It validates every
record before accepting a match and compares canonical JSON instead of Python
boolean/numeric equality. CLI failure output does not print evidence contents.

`tools/verify_signed_release_attestations.py`, called by the existing protected
release workflow, now uses that same strict parser and type-preserving comparison.
Its existing exact source, builder, image repository/digest, subject,
statement-type, predicate-type and SBOM-hash checks remain mandatory.

## Verification

Three synthetic cases reproduced the old generic verifier's false acceptance:
null copy with absent predicate, a boolean replaced by an integer, and malformed
trailing verification after a match. No production evidence or secrets were used.

Local isolated verification:

```sh
python -m pytest -q tests/test_attestation_predicate.py
# 52 passed
python -m compileall -q tools tests
```

The new `tests/test_signed_release_attestation_content.py` exercises the protected
release consumer, including correct content, boolean/number mismatch, duplicate
JSON keys in every layer, empty attestations, and unchanged subject/type/digest
authority. It requires the repository's existing release-tool dependencies and
is included for the full repository CI suite; the isolated local run above is
not evidence that the full repository suite passed.

## Boundaries

Cosign authentication and exact immutable subject verification are prerequisites,
not replaced by this content comparison. Production certification, workload pins,
staging secrets, backup/restore and rollback evidence, host readback, maintenance
windows and independent exact-head review remain separate gates. No signing key,
trust root, image digest, runtime configuration, deployment permission, provider
integration or live-delivery flag is changed.
