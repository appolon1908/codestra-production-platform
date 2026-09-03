# Wave 5 deployment — 2026-09-02

Status: PARTIAL.

- Reseller portal changed from local image `sha256:7d7cf6318ac122f7e39ab679dec499dc1f6116129765903d44e42c74541ca12e` to protected source `e612e38dae1a1e2ec5e770dcd29aabc3c2ea2b53` and immutable image `sha256:74ce88fa3ca05a6c3d595080b78c398be1dc49ac72185ba8aa787d9f6f8247d9`.
- Source publication run: `33696118455`; SBOM, provenance, vulnerability, and OCI source/revision/version checks passed.
- Deployment authority: Platform PR #214, merge `39aeddfe626ff2c17b94884939e3c42810ead669`.
- Existing schema authority was verified before restart; no migration was required. Pre-deployment PostgreSQL dump: `/opt/codestra/backups/reseller-portal-cutover-20260902T234800Z`.
- Post-deployment: healthy, restart count 0, readiness PASS, Prometheus `/metrics` target UP.
- `LIVE_SMS_DELIVERY=false`, `LIVE_EMAIL_DELIVERY=false`, and `LIVE_PSTN_DIALING=false` were verified in the effective container configuration.

Remaining Wave 5 workloads were not changed; Wave 5 is not complete.
