# 15 — Code Quality & Security (Step 24)

Scope: `appolon1908-hue/codestra-production-platform` repo, cloned at `/opt/claude/workspaces/codestra-production-platform`, branch `audit/claude-full-system-readiness-20260825` (== `origin/release/production-activation` @ `bfccda5c`, clean working tree, no local drift). Read-only static checks and the repo's own pre-existing safe tooling only — no dependency upgrades, no fixes applied, no destructive scans run.

## Findings

### SEC-1 — P1 (verify — could be P0 or benign) — Unreviewed hits from the repo's own secret scanner
**Component:** whole repository working tree
**Observed evidence:** ran the project's existing `scripts/audit_repository_secrets.py` (a pre-existing, purpose-built tool — not something introduced by this audit) against the current checkout: `TEXT_FILES_SCANNED=747`, `REDACTED_FINDINGS=44`, `SENSITIVE_OR_LARGE_ARTIFACTS=12`. The tool's output is redaction-by-design — it does not print file paths, line numbers, or values, only counts.
**Expected state:** zero findings from the project's own secret scanner on a repository claimed production-ready, or a documented allowlist explaining each finding.
**Current state:** 44 redacted findings + 12 flagged artifacts, cause and severity unknown from this vantage point.
**Risk:** unknown until reviewed — ranges from false positives (test fixtures, example configs) to an actual committed credential (which would be P0). Per this audit's "redact secrets from all reports" rule, this report cannot respect that rule *and* self-verify the findings, so it is reported at the scanner's own default output level.
**Files/config:** `scripts/audit_repository_secrets.py` (the scanner itself).
**Recommended fix:** someone with authorized access should run the scanner with full (unredacted, or securely-redacted-for-humans-only) output and triage each of the 44+12 hits; anything real gets rotated and purged from history.
**Test required:** re-run scanner after remediation, expect 0 findings or a documented, reviewed allowlist.
**Rollback:** N/A (read-only finding).
**Repo:** appolon1908-hue/codestra-production-platform. **Suggested branch:** `security/secret-scan-triage`.

### SEC-2 — P2 — Stale SBOM/vulnerability evidence
**Component:** `gate3a-release-0359813-sbom.cdx.json`, `gate3a-release-0359813-vulnerability.json` (repo root)
**Observed evidence:** `CreatedAt: 2026-07-23T14:44:06Z` — over 4 weeks old relative to this audit date (2026-08-25). No evidence found within this pass of a recurring/CI-scheduled scan producing fresher artifacts.
**Expected state:** vulnerability/SBOM evidence refreshed on every release or on a defined cadence (e.g. weekly), with a max-age gate blocking "production ready" claims on stale scans.
**Current state:** single scan, over a month old, is the only vulnerability evidence found in-repo.
**Risk:** newly disclosed CVEs in base images/dependencies since 2026-07-23 are not reflected.
**Recommended fix:** wire SBOM/vuln scanning (e.g. Trivy, which produced this schema) into CI on a schedule and on every release tag; add a freshness check to the readiness gate.
**Test required:** confirm new scan artifact timestamp updates automatically.
**Rollback:** N/A.
**Repo:** appolon1908-hue/codestra-production-platform. **Suggested branch:** `ci/recurring-vuln-scan`.

### SEC-3 — P3 — Dependency manifest location unclear at repo root
**Component:** Python dependency management
**Observed evidence:** `pip-audit` is available on the host, but no `requirements*.txt` or `pyproject.toml` was found at the repository root — only `vicidial/pyproject.toml` for the VICIdial-adapter subpackage. Did not locate/audit manifests for the rest of the middleware services within this pass.
**Current state:** UNVERIFIED whether other services (control_plane, eventing, identity, integrations, tel_events, etc. — all present as top-level dirs in this repo) have their own manifests elsewhere or share one not found in this pass.
**Recommended fix:** confirm with the team where each service's dependency manifest lives, then run `pip-audit` (report-only) per manifest as part of Step 24 follow-up.
**Repo:** appolon1908-hue/codestra-production-platform. **Suggested branch:** `chore/dependency-audit-followup`.

### SEC-4 — P2 (flagged for the parent audit's Step 1/19 hygiene, out of strict repo scope) — Large volume of untracked working directories outside the git repo
**Component:** host filesystem — `/root`, `/home/lolo`, `/opt/codestra/worktrees` (137 entries), `/opt/codestra/*-remediation-*`, `*-rehearsal-*`, `*-cert-*`, `*-evidence-*` directories
**Observed evidence:** `find / -iname "*vicidial*" -type d` alone surfaced 60+ directories outside any git working tree, including names like `vicidial-db-pass-rotation-evidence-20260724T190704Z`, `vicidial-backup-evidence-20260723-160000`, `vicidial-safe-test-work` — consistent with dozens of prior agent sessions leaving scratch/evidence directories on the host rather than in a repo or a dedicated, cleaned-up location.
**Expected state:** ephemeral agent working directories cleaned up after use, or consolidated into a single, git-ignored, access-controlled scratch location.
**Current state:** scattered across `/root`, `/home`, and `/opt/codestra` directly, some containing "evidence" of past secret/credential rotations.
**Risk:** unmanaged, non-git-tracked directories are not covered by the repo's secret scanner (SEC-1) or by code review; they may retain stale credentials, and inflate disk usage / incident-response confusion (an on-call engineer cannot tell from naming alone which of ~150 `vicidial-*`/`codestra-*` directories are current).
**Recommended fix:** a dedicated workspace-hygiene sweep (out of scope for this security pass) to inventory, and archive-or-delete these directories; going forward, constrain agent scratch space to one location excluded from `git status`/deploy paths.
**Test required:** N/A — inventory/cleanup task, not a code change.
**Rollback:** N/A.
**Repo:** N/A (host-level, not repo-level). **Suggested branch:** N/A.

## Positive controls observed
- The codebase has **purpose-built governance tooling** that actively rejects placeholder/TODO/TBD values in production configuration: `operations/monitoring/validate-governance.py`, `operations/canary/validate-authorization.py`, `operations/monitoring/validate-receiver-files.py`, each with a regex specifically matching `TBD|TODO|UNKNOWN|PLACEHOLDER|BLOCKED|ABSENT|NONE(|UNASSIGNED)`. All 8 `TODO|FIXME|NotImplementedError|# stub|placeholder` hits found by a full-repo grep are *inside these validators and their tests* — none is unfinished production code. No stub/mock/`NotImplementedError` found in production code paths within this pass.
- The repo ships its own secret-scanning tool (`scripts/audit_repository_secrets.py`) that scans 747 text files and reports redaction-safe counts by design — good practice for automated CI use, even though it means this audit could not itself triage SEC-1's findings.
- Branch is current with `origin/release/production-activation` (`bfccda5c`), clean working tree — no undocumented local drift on the branch used for this audit.

## Not run in this pass (deferred, with reason)
- Full `pytest` suite: deferred — `pytest.ini` exists, but without confirming test fixtures are fully isolated from live production databases/services, running the suite risked violating the Phase 1 read-only mandate. Recommend running in a follow-up with an explicitly isolated test compose stack.
- Lint/type-check tooling: not located/run within this pass's time budget — recommend a follow-up pass identifying the configured linter (ruff/flake8/mypy) per service directory.
- `pip-audit` execution: tool is present but no root-level manifest found to run it against (see SEC-3).
