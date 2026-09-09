# Production certification reconciliation

## Purpose

`PRODUCTION-SOURCE-LOCK.yaml` and `IMMUTABLE-CANDIDATE-MATRIX.yaml` are production authorities. Their status fields may not be changed to `PASS` or `deployment_authorized=true` merely to unblock a workflow. The supporting evidence must first prove the exact protected source, immutable artifact, runtime identity, rollback candidate, API alignment, recovery and canary gates.

The repository-owned validator is:

```text
tools/reconcile_production_certification.py
```

Its structural mode verifies that incomplete evidence remains truthfully fail closed. Its `--require-complete` mode is the final source gate and fails until all mandatory evidence is complete.

## Required workload evidence

Exactly 64 workload records are required. Each record must identify:

```text
canonical repository
protected 40-character source SHA
OCI image by repository@sha256 digest
signature reference
SBOM reference
provenance reference
configuration checksum
runtime source readback
runtime digest readback
previous rollback source SHA
previous rollback image digest
```

The forward and rollback candidates must not be identical. `latest`, zero values, `UNKNOWN`, `PENDING`, `NOT_RUN`, `NOT_STARTED`, `TBD`, `TODO`, and replacement placeholders are rejected by the final gate.

## Required business API evidence

Exactly 15 application records are required. Each must prove:

```text
health=PASS
readiness=PASS
version=PASS
capabilities=PASS
OpenAPI source/runtime alignment=PASS
gateway/application alignment=PASS
runtime source and image attribution=PASS
```

The record must include the exact protected source SHA and immutable runtime image digest. A route declaration or successful build is not runtime API evidence.

## Canonical evidence rule

Evidence is canonical only when it originates from the owning protected authority:

- Git source identity from the protected repository branch or reviewed merge commit;
- OCI digest from the signed registry artifact produced from that source;
- signature, SBOM and provenance from the artifact build and verification workflows;
- runtime source/digest identity from the deployed workload itself or an authenticated orchestrator readback;
- gateway alignment from the protected Kong route authority and live read-only route export;
- backup, restore and rollback from isolated execution against the exact candidate;
- staging-host identity from the approved `Infustruction-repo` provisioning workflow;
- canary evidence from the protected maximum-one-percent GET/HEAD-only production workflow.

Local notes, branch names, mutable tags, uncommitted server files, inferred digests, and copied historical evidence are not canonical.

## Required sequence

```text
1. Resolve canonical Middleware source and image authority.
2. Complete signed immutable artifacts for all 64 workloads.
3. Populate runtime source/digest and rollback readback.
4. Provision and verify the isolated staging host.
5. Populate and checksum the staging-readonly endpoint manifest.
6. Run 15/15 API and 29-route alignment certification.
7. Run backups, isolated restores and rollback.
8. Run the protected read-only staging certification.
9. Run the maximum one-percent GET/HEAD-only production canary.
10. Complete soak and update the source lock and candidate matrix from the resulting evidence.
11. Execute the final `--require-complete` gate.
```

## Safety boundary

Until the final gate passes:

```text
deployment_authorized=false
production_canary_authorized=false
production_certified=false
```

No source-only merge authorizes a server deployment, a secret installation, an external delivery, a business write, a campaign, a payment or a financial/trading action.
