# Wave 4 deployment — 2026-09-02

Status: PARTIAL.

- Mail API changed from local image `sha256:7495d5f0d79f027456ed61b7c3c2ea9331c228f3d2e10bceef3178eef5a62594` to protected source `e612e38dae1a1e2ec5e770dcd29aabc3c2ea2b53` and immutable image `sha256:586ed6aaded359b4cad64905d027079ea910eda5202bae0bac0d44d8baf0df09`.
- Source publication run: `33696118455`; SBOM, provenance, vulnerability, and OCI source/revision/version checks passed.
- Deployment authority: Platform PR #214, merge `39aeddfe626ff2c17b94884939e3c42810ead669`.
- Pre-deployment SQLite backup: `/opt/codestra/backups/mail-api-cutover-20260902T234700Z`; checksum and integrity checks passed.
- Post-deployment: healthy, restart count 0, readiness PASS, Prometheus `/metrics` target UP.
- No email, SMS, PSTN, social, advertising, model, or n8n provider effect was enabled.

The remaining provider-bound workloads were not changed; Wave 4 is not complete.
