# Production certification evidence refresh

This repository owns the fail-closed production source lock. The runtime candidate matrix remains owned by `appolon1908-hue/codestra-production-runtime-authority`.

## Purpose

The evidence verifier checks the committed lock and immutable candidate matrix without manufacturing a passing state. It accepts only real repository SHAs, digest-bound images, signatures, SBOMs, provenance, rollback digests, exactly 64 workload identities, and an explicitly authorized matrix. It can additionally verify every referenced commit through the GitHub API.

A successful unit-test workflow proves only that the verifier is fail closed. The production gate passes only when a protected manual run against the final committed authorities reports:

```text
PRODUCTION_CERTIFICATION_EVIDENCE=PASS
FINDINGS=0
```

## Required sequence

1. Resolve the canonical Middleware lineage through protected source, exact-head CI, independent approval, immutable build, and staging evidence.
2. Record the final protected source SHA for every workload authority.
3. Record one immutable OCI digest, signature, SBOM, provenance reference, and rollback digest for each of 64 workload identities.
4. Set matrix deployment authorization only after its own protected review and all prerequisite evidence passes.
5. Update `PRODUCTION-SOURCE-LOCK.yaml` from those exact authorities.
6. Run this verifier with GitHub commit verification enabled.
7. Materialize the staging endpoint manifest from the verified lock and matrix; never type a second competing candidate by hand.

## Forbidden shortcuts

- changing `FAIL` to `PASS` without replacing the blocking evidence;
- accepting `UNKNOWN`, `PENDING`, placeholders, local-only image IDs, or mutable tags;
- silently choosing one of two conflicting Middleware lineages;
- using a running legacy container as immutable release evidence;
- treating a skipped job, startup failure, or zero-job Actions run as success;
- recording secret values in GitHub artifacts or repository evidence;
- allowing this evidence-refresh workflow to deploy, contact a server, or enable production effects.

## Manual gate example

```bash
python3 tools/verify_production_certification_evidence.py \
  --source-lock PRODUCTION-SOURCE-LOCK.yaml \
  --matrix /secure/input/IMMUTABLE-CANDIDATE-MATRIX.yaml \
  --verify-github \
  --require-pass \
  --evidence-output /secure/evidence/production-certification-evidence.json
```

The generated JSON is secret-free and may be sanitized and committed after review. The matrix and source lock remain separate authorities and must be updated in their owning repositories.
