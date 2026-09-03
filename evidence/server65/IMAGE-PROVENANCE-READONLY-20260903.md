# Server 65 image provenance read-only refresh

Date: 2026-09-03
Target: `65.109.65.169`
Access: existing `codestra-app` alias as `codestra-admin`; Docker inspect only.

## Aggregate read-back

- Running containers inspected: `106`
- Image declarations containing `@sha256:`: `77`
- Mutable image declarations (no digest): `29`
- Containers with a Docker `RepoDigests` read-back: `0/106`
- Missing `org.opencontainers.image.source`: `43/106`
- Missing `org.opencontainers.image.revision`: `59/106`

Digest syntax in a Compose/image declaration is not sufficient when the local
engine has no RepoDigest read-back. The missing OCI labels and 29 mutable
declarations prevent immutable source-authority certification. This is a
read-only observation; no image pull, tag, delete, or restart was performed.

IMMUTABLE_IMAGES=FAIL
SOURCE_AUTHORITY=FAIL
SOURCE_RUNTIME_DRIFT=UNVERIFIED
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
