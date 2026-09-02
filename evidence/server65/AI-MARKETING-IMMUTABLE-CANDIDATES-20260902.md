# AI and Marketing immutable candidate evidence

Captured: 2026-09-02T22:52:00Z

This evidence records release candidates only. Neither image was deployed to staging or production.

## Codestra AI

- Protected source merge: `7d31ef8de1c15bcc71b61de50917c81e3bcf557d`
- Source PR: `https://github.com/appolon1908-hue/Codestra-AI/pull/8`
- Protected publication workflow: `https://github.com/appolon1908-hue/Codestra-AI/actions/runs/33691179307`
- Immutable image: `ghcr.io/appolon1908-hue/codestra-ai@sha256:908c59e54a2620142e597523fa31b5d1d710dc00156b35c5a642e5437362df3e`
- Registry package version: `1202541064`
- Registry read-back user: `10001:10001`
- OCI source: `https://github.com/appolon1908-hue/Codestra-AI`
- OCI revision: `7d31ef8de1c15bcc71b61de50917c81e3bcf557d`
- OCI version: `sha-7d31ef8de1c15bcc71b61de50917c81e3bcf557d`
- OCI created: `2026-09-02T22:20:09Z`
- Build policy: BuildKit `provenance: mode=max`, `sbom: true`

## Codestra Marketing

- Protected source merge: `fe784f1e91bb0f0fd49f2b2f741a4020a337c149`
- Corrective source PR: `https://github.com/appolon1908-hue/Codestra-Marketing-/pull/9`
- Protected publication workflow: `https://github.com/appolon1908-hue/Codestra-Marketing-/actions/runs/33691315107`
- Immutable image: `ghcr.io/appolon1908-hue/codestra-marketing@sha256:3d9bd44922ad02d865f191cac5c9e454b88bb7cbfc8cd643f81e7b57f132c391`
- Registry package version: `1202544721`
- Registry read-back user: `10001:10001`
- OCI source: `https://github.com/appolon1908-hue/Codestra-Marketing-`
- OCI revision: `fe784f1e91bb0f0fd49f2b2f741a4020a337c149`
- OCI version: `sha-fe784f1e91bb0f0fd49f2b2f741a4020a337c149`
- OCI created: `2026-09-02T22:21:22Z`
- Build policy: BuildKit `provenance: mode=max`, `sbom: true`

## Read-back method

Package digests and immutable tag bindings were read through the GitHub Packages API. Image configuration and OCI labels were read by exact digest through BuildKit image inspection. No registry credentials, tokens, or image-embedded secrets are included here.

The first Marketing image at protected source `599bcd7dae4543ec67f421d39cec47b91cacbf69` is superseded because its Dockerfile did not enforce the committed dependency lock. It is not a promotion candidate. PR #9 corrected the build and published the digest recorded above.
