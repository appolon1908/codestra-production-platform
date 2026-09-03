# Wave 4 deployment — 2026-09-02

Status: PARTIAL.

- Mail API changed from local image `sha256:7495d5f0d79f027456ed61b7c3c2ea9331c228f3d2e10bceef3178eef5a62594` to protected source `e612e38dae1a1e2ec5e770dcd29aabc3c2ea2b53` and immutable image `sha256:586ed6aaded359b4cad64905d027079ea910eda5202bae0bac0d44d8baf0df09`.
- Source publication run: `33696118455`; SBOM, provenance, vulnerability, and OCI source/revision/version checks passed.
- Deployment authority: Platform PR #214, merge `39aeddfe626ff2c17b94884939e3c42810ead669`.
- Pre-deployment SQLite backup: `/opt/codestra/backups/mail-api-cutover-20260902T234700Z`; checksum and integrity checks passed.
- Post-deployment: healthy, restart count 0, readiness PASS, Prometheus `/metrics` target UP.
- Email reseller changed from local image `sha256:8d7bb50e8787c110a7930fadb0c69a44ba075c70cb5e035118d9f334b1211e08` to protected source `e612e38dae1a1e2ec5e770dcd29aabc3c2ea2b53` and immutable image `sha256:1dba872104d8876b6e9882b9d629a5b767358eb55ce93b626331f4d92b5035d4`.
- Email-reseller deployment authority: Platform PR #219, merge `e05873b7555f228cb98eecc15f090a9eead509b7`.
- Email-reseller rollback files and runtime snapshot: `/opt/codestra/backups/email-reseller-cutover-20260903T001500Z`; no migration was run.
- Email-reseller post-deployment: healthy, restart count 0, `/livez`, `/readyz`, and `/health` PASS; synthetic submission mode and live email/SMS/PSTN flags remain false.
- Email-reseller `/version`, `/capabilities`, and `/metrics` return 401 and therefore remain explicit API-certification gaps.
- No email, SMS, PSTN, social, advertising, model, or n8n provider effect was enabled.

The remaining provider-bound workloads were not changed; Wave 4 is not complete.
