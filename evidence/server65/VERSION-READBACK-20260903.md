# Runtime version read-back

Date: 2026-09-03
Target: `65.109.65.169`
Access: loopback HTTP GETs only; no credentials or mutations.

| Service | HTTP | Selected read-back |
|---|---:|---|
| Middleware API (`8096/version`) | 200 | service `codestra-control-plane`; release_id present; image_digest `unknown` |
| Reseller (`18180/version`) | 200 | environment `production`; git SHA and image digest present |
| Portal (`18081/version`) | 404 | standard version contract absent |
| Staging Middleware (`31883/version`) | 200 | release_id `unknown`; image_digest `unknown` |

The production Middleware version response does not report an image digest,
and the staging response reports unknown release identity. This independently
prevents exact runtime source-lock read-back, even where Docker configuration
uses a digest-addressed image.

VERSION_ENDPOINTS=FAIL
SOURCE_RUNTIME_DRIFT=UNVERIFIED
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
