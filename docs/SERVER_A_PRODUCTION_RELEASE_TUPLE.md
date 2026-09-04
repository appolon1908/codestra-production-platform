# Server A protected production release tuple

The release tuple is a versioned, machine-readable source authority. It does not
self-authorize deployment.

| Element | Authority | Exact candidate | Runtime status |
| --- | --- | --- | --- |
| Platform orchestration and evidence | `appolon1908-hue/codestra-production-platform` | protected merge and signed post-merge release | repository candidate |
| Middleware source and image | `appolon1908-hue/Middleware-` | `1aa4d505846b7494aff94bec3d7ea68c895e2dd3` / `sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504` | signed immutable candidate, not deployed |
| Former Middleware authority | `Codestra-SRL/codestra-middleware` | `f199b6c40f4e467979e9a8b255a0e686321a182d` / `sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b` | historical rollback reference only |

The selected Middleware evidence is artifact `signed-middleware-release-1aa4d505846b7494aff94bec3d7ea68c895e2dd3-33767657962-1` from run
`33767657962`, artifact ID `9898309168`. The platform verifier binds the archive,
release manifest, Sigstore bundle, SPDX SBOM, vulnerability report, image
signature, provenance, source labels, and migration head.

## Out-of-band release trust anchor

The **Out-of-band release trust anchor** is provisioned separately from this
repository and from the release payload. Its approved SSH signer authority is
installed at `/etc/codestra/release/allowed_signers`; the exact public-key
fingerprint must be approved through the protected release ceremony and installed
by `tools/provision_release_trust_anchor.py` using the expected SHA-256 guard. A
candidate may not replace, silently rotate, or derive this trust anchor from its
own manifest, image, artifact, or workflow token. If a different trust anchor is
already installed, deployment fails closed and requires a separate reviewed
rotation change.

The tuple keeps `production_deployment_authorized=false`. Promotion requires the
global source lock to pass, exact-digest staging certification, paired backup and
restore evidence, two-way rollback, a read-only canary no greater than one
percent, and a separate traffic-activation decision. External-effect flags
remain false.
