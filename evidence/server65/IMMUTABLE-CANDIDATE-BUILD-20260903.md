# Immutable candidate build evidence

Date: 2026-09-03
Server scope: 65.109.65.169 (evidence only; no host mutation)

## Protected workflow

- Repository: `appolon1908-hue/codestra-production-platform`
- Workflow: `immutable-candidate-build`
- Run: https://github.com/appolon1908-hue/codestra-production-platform/actions/runs/33700200254
- Exact head SHA: `517145689b6a27c9953ffd357458d8fc8e7c100d`
- Result: `success`
- Completed: `2026-09-03T00:46:59Z`
- Protected release tag: `protected-517145689b6a27c9953ffd357458d8fc8e7c100d`
- Protected release workflow: https://github.com/appolon1908-hue/codestra-production-platform/actions/runs/33700200216
- Middleware release digest read back by the protected workflow:
  `sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b`

The rerun completed all four matrix builds (integration-control-plane,
reseller-portal, mail-api, and email-reseller). Each job passed the local
security candidate build, Trivy scan, digest-addressed build/push, immutable
candidate evidence verification, and artifact upload.

The first attempt exposed a GHCR digest read-back propagation failure for
`reseller-portal`; the protected rerun passed. This is candidate-build evidence
only and does not establish deployment to Server 65.

SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
