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
- Email-reseller operational API source merged in Platform PR #221 at `9371bc39b11fe2cd52c5414e84a31cc9adb80644`; protected publication run `33699390261` produced digest `sha256:e1dddbb9055528b702dd27d99b42ee59b1929a2de826ca966075bd0b59e5e005` with SBOM, provenance, vulnerability, and OCI gates passing.
- Digest authority PR #222 auto-merged normally at `f46d07510158f4dcac3ef482a6f871dde2b8acde`. A first replacement attempt was immediately rolled back because the pre-deploy actionable-alert count was 1. The alert was the disk-capacity warning; no application or monitoring degradation occurred.
- After removing 3.93 GB of abandoned `/tmp` test environments, disk utilization fell to 74.34% and the alert resolved. The replacement was repeated from a green baseline.
- Final email-reseller runtime: protected SHA `9371bc39b11fe2cd52c5414e84a31cc9adb80644`, exact digest `sha256:e1dddbb9055528b702dd27d99b42ee59b1929a2de826ca966075bd0b59e5e005`, healthy, restart count 0. `/livez`, `/readyz`, `/health`, `/version`, and `/capabilities` return attributable, non-cached responses; all external-delivery capability values are false and simulation is true.
- Email-reseller `/metrics` remains an explicit API/observability gap and is not counted as certified.
- No email, SMS, PSTN, social, advertising, model, or n8n provider effect was enabled.

The remaining provider-bound workloads were not changed; Wave 4 is not complete.
