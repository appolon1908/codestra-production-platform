# Unfixed high-severity middleware risk packet

Decision state: `AWAITING_AUTHORIZED_SECURITY_RISK_OWNER`

This packet does not accept risk and does not authorize release promotion.

## Exact artifact and scanner

- Image:
  `codestra/gate3a-release@sha256:23ebbcdf07eb475adf628175c9450056188a4fdcaebff6e8e5716245df5581c0`
- Scanner:
  `aquasec/trivy@sha256:086971aaf400beebd94e8300fd8ea623774419597169156cec56eec5b00dfb1e`
- Trivy version: `0.66.0`
- Refreshed database date: `2026-07-26`
- Raw result SHA-256:
  `fffccdfe7c6cb8ae687ad10711b45d5241877ebb370902e7d03ea130cd9f0854`
- CycloneDX SBOM SHA-256:
  `196351cefcb1de39841a3e8fc42e69542bba0e75999262776718bb4d6aafc010`

## Findings

The exact digest contains 21 high-severity occurrences and zero critical
occurrences. Trivy reports no fixed version for any occurrence.

- `libexpat1`: CVE-2025-59375, CVE-2026-25210, CVE-2026-45186,
  CVE-2026-56131, CVE-2026-56407, CVE-2026-56408
- `libncursesw6`, `libtinfo6`: CVE-2025-69720
- `libpython3.13-minimal`, `libpython3.13-stdlib`, `python3.13-minimal`,
  `python3.13-venv`: CVE-2026-11940, CVE-2026-15308, CVE-2026-7210
- `libuuid1`: CVE-2026-53615

The current upstream digest for `gcr.io/distroless/python3-debian13:nonroot`
still resolves to the already pinned
`sha256:0e52dfee02b1aba142e77b004f6ea11210b79456b51f10d70e9bd631cbc21d98`.
No compatible base refresh is presently available through that reference.

## Required independent decision

An authorized security/risk owner must validate exploitability, identify
compensating controls, assign an owner and expiry, and record an explicit
signed decision. Until then:

`VULNERABILITY_REMEDIATION_GATE=BLOCKED_UNFIXED_HIGHS_AWAITING_EXTERNAL_DECISION`
