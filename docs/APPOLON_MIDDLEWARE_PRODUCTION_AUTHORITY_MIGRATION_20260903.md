# Appolon Middleware production authority migration — 2026-09-03

## Decision

Promote `appolon1908-hue/Middleware-` as the canonical Middleware source and image authority for the next protected production release, subject to exact-head CI, independent review, signed platform release verification, protected staging certification, backup/restore rehearsal, rollback proof, read-only canary, observation window, and final public-edge validation.

Retain `Codestra-SRL/codestra-middleware` only as a non-promotable rollback authority until post-cutover retirement is separately reviewed.

## Exact candidate

- Repository: `appolon1908-hue/Middleware-`
- Protected source SHA: `1aa4d505846b7494aff94bec3d7ea68c895e2dd3`
- Immutable image: `ghcr.io/appolon1908-hue/codestra-middleware@sha256:cec8b5a186866a4ce77a6079cb3ab6fdb2a3487003872e678b9caa90c1ae52e5`
- Signed release run: `33767657962`
- Evidence artifact: the single unexpired artifact produced by that exact run

The artifact name, builder identity, SBOM hash, provenance hash, and OpenVEX hash must be read from and verified against the downloaded release evidence; they must not be guessed.

## Safety boundary

This authority migration changes repository release controls only. It does not deploy a container, run a database migration, alter SSH, route production traffic, enable a business write, call a provider, send email or SMS, place a call, write to Odoo, or activate n8n delivery.

The following remain mandatory throughout the web-traffic cutover:

```text
LIVE_SMS_DELIVERY=false
LIVE_EMAIL_DELIVERY=false
LIVE_PSTN_DIALING=false
LIVE_WRITE=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false
CALLBACK_DISPATCH=false
CALLS_PLACED=0
```

## Required protected sequence

After the authority PR is independently approved and merged, produce a new signed platform release, install the exact restricted operator tuple through the documented root-only installer, and execute:

`preflight` → `backup` → `validate-backup` → `restore-test` → `stage` → `stage-control-plane` → `validate-control-plane` → `rollout-middleware` → `canary` → `collect-evidence` → `observation-window` → `enable-production-web-traffic` → `status`.

Any source or digest mismatch, readiness failure, monitoring loss, database drift, migration mismatch, latency/error regression, write request, external-effect movement, or failed public-edge readback requires an immediate stop and rollback.
