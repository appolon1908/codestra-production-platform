# Gate 3A clean-build reproducibility and security evidence

Evidence timestamp: `2026-07-23T14:44:09Z`  
Host: `middleware`  
Environment: two detached clean Git worktrees and isolated local Docker builds  
Production deployment: not performed

```text
SOURCE_COMMIT=0359813771558658ed417a63915cae9a4caf5792
BRANCH=feature/callcenter-platform-19
CLEAN_BUILD_RUNS=2
CLEAN_BUILD_RESULT=PASS_EQUIVALENT
SOURCE_ARCHIVE_SHA256=ad101a7dfd509cb5f03c90a0608c327fdc5ad07ed6bbb349890aba1a65ee8ec0
IMAGE_DIGEST=sha256:23ebbcdf07eb475adf628175c9450056188a4fdcaebff6e8e5716245df5581c0
RUN_G_TESTS=PASS_34_SKIPPED_1_DATABASE_PROVISIONING
RUN_H_TESTS=PASS_34_SKIPPED_1_DATABASE_PROVISIONING
RUFF=PASS_BOTH_RUNS
MYPY=PASS_24_FILES_BOTH_RUNS
RUNTIME_HEALTH=PASS_HTTP_200
RUNTIME_USER=65532:65532
RUNTIME_READ_ONLY_ROOTFS=PASS
RUNTIME_CAPABILITIES=DROPPED_ALL
RUNTIME_NO_NEW_PRIVILEGES=PASS
```

Both clean worktrees produced the same source archive SHA-256 and, using
`docker build --no-cache --provenance=false`, the same final OCI image digest.
The runtime is a digest-pinned, non-root, distroless Python 3.13 image. The
builder is also digest-pinned. Git metadata, caches, reports, credentials, and
private-key paths are excluded from the Docker context.

The runtime smoke test started the image with a read-only root filesystem,
all Linux capabilities dropped, `no-new-privileges`, and only a bounded
loopback port. `GET /healthz` returned HTTP 200 with dry-run mode and
authorization offline. The container was stopped after the test.

## Dependency and vulnerability result

FastAPI was upgraded from `0.116.1` to `0.139.2` and Starlette from `0.47.3`
to `1.3.1`. Production images exclude pytest, Ruff, and mypy.

```text
CRITICAL_FINDINGS=0
HIGH_FINDINGS=17
FIXED_VERSION_AVAILABLE_FOR_HIGH_FINDINGS=0
PYTHON_PACKAGE_HIGH_OR_CRITICAL_FINDINGS=0
SECURITY_GATE=NO_GO_UNPATCHED_DISTROLESS_BASE_FINDINGS
```

The remaining findings are Debian/distroless OS packages for which the
scanner reported no fixed version: libexpat, ncurses/tinfo, libuuid, and
Python 3.13 standard-library packages. They are not suppressed or represented
as passed. A refreshed upstream distroless digest must be scanned before
release, and the gate remains no-go until policy accepts or eliminates them.

## Evidence checksums

```text
VULNERABILITY_JSON_SHA256=6a9de34a001e8791bc09664ed47a8c3bf829f21df8f10ac38aef23121d5a7477
SBOM_CYCLONEDX_SHA256=ff4119f85870abf268cb79d07968b9e21bffbe8eb51db3d127653949bafafdec
```

Evidence files:

- `gate3a-release-0359813-vulnerability.json`
- `gate3a-release-0359813-sbom.cdx.json`

