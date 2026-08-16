# Secret-scan classification — 2026-08-16

`gitleaks detect --redact` scanned 170 commits and reported no leaks. The repository-specific redacting heuristic produced 30 findings without emitting values.

- **False positives (24):** runtime assignments whose values come from environment variables, root-only/read-only secret files, request parsing, function parameters, or generated in-memory values. These include the control-plane, Odoo bridge, verification tooling, telephony publisher, and VICIdial runtime sources.
- **Test fixtures (6):** synthetic credential-shaped constants in `tests/test_integration_control_plane.py` and scanner-classification fixtures in `vicidial/tests/test_adapter.py`.
- **Historical secrets (0):** none identified by the repository history scan.
- **Active secret exposure (0):** none identified; no rotation was warranted.

The classification is based on source provenance and the clean history-aware Gitleaks result. Runtime credential values were not printed or copied into evidence.
