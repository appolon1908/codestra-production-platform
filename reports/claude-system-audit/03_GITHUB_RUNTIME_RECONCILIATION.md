# 03 — GitHub / Runtime Reconciliation (STEP 2)

Scope: codestra-app host (65.109.65.169) only, per audit scope decision. Read-only. No writes, merges, or pushes performed.

## 0. Critical structural discovery

The repository the parent audit was pointed at — **`appolon1908-hue/codestra-production-platform`**
(public, personal account) — is an **aggregation/release-tuple repo**, not the source of truth for
the individual services actually running on this host. Its own doc,
`docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md`, states this explicitly: it holds orchestration/JetStream/
policy/evidence tooling; the actual **middleware executable source lives in a separate GitHub
organization, `Codestra-SRL`** (8 private repos, billing email `appolon1908@gmail.com` — same owner,
different org). None of the on-disk service checkouts under `/opt/codestra/*` point at
`appolon1908-hue/*` at all — they point at `Codestra-SRL/*` (GitHub) or legacy `bitbucket.org` remotes.

`Codestra-SRL` repos found: `codestra-odoo-addons`, `codestra-middleware`, `codestra-n8n-workflows`,
`codestra-server-c`, `telephony-event-gateway` ("Server B"), `codestra-financial-service`,
`codestra-financial-governance`, `codestra-ai-platform`.

Any future audit/agent work must treat `Codestra-SRL/*` as authoritative for service code, and
`appolon1908-hue/codestra-production-platform` as authoritative only for infra/orchestration policy —
conflating them (as the initial task setup did, cloning only the personal-account repo) will miss the
real drift.

## 1. Local checkouts under /opt/codestra — remote/branch/SHA/dirty state

| Path | Remote | Branch | SHA | Dirty | Notes |
|---|---|---|---|---|---|
| `agent-desktop` | **local path** `/opt/codestra/quarantine/agent-desktop-unapproved-20260725T233810Z` (not GitHub) | staging/sipjs-webrtc-20260726 | 4063a08 | 15 files | "origin" is not a real remote — points at a local quarantined directory. No live upstream. |
| `middleware` | `github.com/Codestra-SRL/codestra-middleware.git` | postiz-social-orchestration-20260804 | 7b9451b | 15 files | On-disk checkout is a stale feature branch, not what's actually deployed (see §2). |
| `contact-center-middleware` | none | `master`, **zero commits** | — | 3 files | Not a real repo — empty `git init` with uncommitted files sitting in it. |
| `identity-platform` | none configured in this check | feature/callcenter-platform-19 | 791b706 | 5 files | |
| `frontend` | `bitbucket.org/sip887/frontend.git` | feature/codestra-customer-portal | c5e79af | clean | Still on Bitbucket, not migrated to either GitHub org despite `bitbucket-codestra` "migration" directory existing elsewhere. |
| `vicidial-odoo-sync` | none configured in this check | rebuild/test-syn-odoo-import | 0d3e837 | 3 files | |
| `odoo-addons` | `github.com/Codestra-SRL/codestra-odoo-addons.git` | odoo19-middleware-security-role-20260804 | fa32b9e | 12 files | |
| `contracts` | none | contracts/v1 | bf00a39 | 8 files | |
| `n8n-workflows` | `github.com/Codestra-SRL/codestra-n8n-workflows.git` | feature/n8n-automation-blueprint | b39f26f | 7 files | |
| `bitbucket-codestra` | `bitbucket.org/codestra902101/codestra.git` | agent/github-migration | 62b353a | clean | |
| `integration-tests` | none | `master`, zero commits | — | clean | Empty scaffold. |
| `automation` | none | `master`, zero commits | — | clean | Empty scaffold. |
| `sip-provisioning` | none configured in this check | integration/durable-state-final | f558115 | 16 files | |
| `telephony-event-gateway-lifecycle-dev` | `github.com/Codestra-SRL/telephony-event-gateway.git` | feature/telephony-lifecycle-contract-v1 | d0ea394 | 12 files | |
| `odoo19-call-center-addons` | none | feature/phase1-foundation | 41c8d3f | **39 files** | Heaviest local drift of any checkout. |
| `odoo19-vertical-addons` | none | staging/vertical-suite-20260726 | 41801bf | 2 files | |

**Finding GH-01 (P2):** Every single working checkout above is on a non-default feature/staging branch
with uncommitted local changes (2–39 dirty files each), none on `main`. These are development
worktrees, not deployment sources — the actual deployed artifacts are pre-built container images (see
§2), so this drift doesn't directly affect runtime, but it means **the on-disk repo trees under
`/opt/codestra` cannot be used to reason about what's running** — only the image labels can.

**Finding GH-02 (P3):** `contact-center-middleware`, `integration-tests`, and `automation` are `git init`
scaffolds with no commits and no remote — dead weight, or possibly aborted setup from an earlier agent
session.

## 2. Deployed image ↔ GitHub commit mapping (highest-value finding)

Checked the core `codestra-middleware-1` container (image tag `codestra/middleware:health-contract-b3ca9aa`):

- Label `io.codestra.build.revision` = `b3ca9aa458fef843e3065aeff3397c656349f138`
- That commit **is real** and merged into `Codestra-SRL/codestra-middleware` via **PR #197**
  ("fix(security): enforce governed VICIdial tenant scope"), merged 2026-08-11.
- `Codestra-SRL/codestra-middleware` `main` is currently at commit `d178cdea2` (merge of PR #262,
  2026-08-22/23) — **219 commits ahead** of what's running in production.
- Critically, **PR #219** ("Add fail-closed JetStream runtime transport", merged 2026-08-14) has **not
  reached production** — and `docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md` in the orchestration repo
  names *exactly this* ("JetStream publisher and DLQ worker") as a component whose production identity
  must be "PR 219 exact protected merge SHA". Production is running code from **before** that PR
  existed.
- The running image is **not** sourced from the pinned registry the release-tuple doc requires
  (`ghcr.io/codestra-srl/codestra-middleware@sha256:<digest>`). `docker image inspect` shows its
  `RepoDigests` as `codestra/middleware@sha256:5dd751a9...` — a **locally built/tagged image**
  (mutable tag `health-contract-b3ca9aa`), not a pull of a signed `ghcr.io` digest. The doc explicitly
  states: *"The release gate must reject feature-branch SHAs, mutable image tags, a staging-only
  approval, absent signatures, or any mismatch found by runtime readback."* The running container fails
  every one of those criteria simultaneously (feature-derived local tag, mutable tag, no visible
  signature verification at this layer).
- Good news: the running digest (`sha256:5dd751a9...`) is **not** the specific digest the doc calls out
  as forbidden-for-production (`sha256:2e153993...`, "authorized for isolated staging only") — so at
  least that specific named landmine wasn't hit. But the broader policy (signed, digest-pinned,
  registry-sourced release) is not being followed for the container actually serving traffic.

**Finding GH-03 (P0):** Production middleware (`codestra-middleware-1`, the container backing
`app.eventing.jetstream` / `app.entrypoints.jetstream_dlq_worker` per the release-tuple doc) is running
from a **locally tagged, mutable image 219 commits / ~11 days behind** `Codestra-SRL/codestra-middleware`
`main`, sourced outside the documented signed-digest release pipeline. This directly contradicts the
repo's own `docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md` release-gate policy and means production is
missing 11 days of merged fixes/features, including the fail-closed JetStream transport work the same
doc names as a required production component.
- Repo: `Codestra-SRL/codestra-middleware`
- Files: running config n/a (image-level); policy doc `docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md` in
  `appolon1908-hue/codestra-production-platform`
- Recommended fix: build/pull the pinned `ghcr.io/codestra-srl/codestra-middleware@sha256:...` digest
  for the intended PR #219 (or later, reconciled) merge SHA, verify signature per
  `tools/provision_release_trust_anchor.py`, redeploy via the documented gate, and retire local mutable
  tags (`health-contract-*`, `webhook-cert-pg-*`, `breero-*`, `n8n-redis-runtime-*`, etc. — dozens exist
  in `docker images`, see §3) from any code path that can reach a running container.
- Test required: re-run the release-gate script against the new digest before cutover; confirm JetStream
  DLQ worker fail-closed behavior end-to-end in staging first.
- Rollback: keep current image available for immediate redeploy if the newer digest regresses.
- Suggested branch: `agent/production-middleware-release-tuple-reconciliation`

Other component images (spot-checked, less deep provenance tracing done — mark UNVERIFIED for exact
commit mapping):
- `codestra-odoo-1`: `odoo@sha256:f54272f31d5f...` — vendor Odoo base image, not a Codestra-built
  artifact by itself (custom addons are mounted/installed at container start per the `ps aux` output
  seen elsewhere in this audit — addons path includes `/mnt/r1-addons`, `/mnt/reviewed-addons`,
  `/mnt/extra-addons`). UNVERIFIED which exact addon commit is mounted; needs a follow-up check of the
  bind-mount source paths against `Codestra-SRL/codestra-odoo-addons` SHAs.
- `codestra-kong-kong-gateway-1`: stock `kong/kong-gateway:3.14.0.1-ubuntu` — vendor image, config-driven
  (see Kong report for whether declarative config in repo matches loaded config).
- `codestra-identity-keycloak-1`: stock `quay.io/keycloak/keycloak@sha256:...` — vendor image, config/realm-driven.

**Finding GH-04 (P2, UNVERIFIED scope):** `docker images` on this host lists dozens of locally-built,
throwaway-named middleware images that are not obviously garbage-collected: `codestra-middleware-final-test`,
`codestra-middleware-policy-auth-test`, `codestra-middleware-campaign-action-test`,
`codestra-middleware-n8n-jwt-guard:test`, `codestra-middleware-results-route:test`, and more, all ~2 days
old, several hundred MB each. These appear to be leftovers from prior agent test/remediation runs (see
§4). Not a runtime risk by themselves (unused images), but they consume the ~68GB of remaining disk
(84% full per host inventory) and make "what image is authoritative" harder to answer at a glance.
Recommend `docker image prune` review (not performed — out of scope for read-only Phase 1) and tighter
tagging discipline (require pinned digests, forbid `:test`/`:local`/ad-hoc suffixes from ever being
`docker run` on this host).

## 3. GitHub-side state (Codestra-SRL, appolon1908-hue)

- `Codestra-SRL/codestra-middleware`: `main` @ `d178cdea2` (PR #262 merge, 2026-08-22/23). 219 commits
  ahead of production. CI/PR status of intervening PRs not exhaustively checked (would require walking
  ~65 PRs #197→#262); flagged as **UNVERIFIED** whether all of them are safe to ship as a batch or
  whether some were themselves later reverted/superseded.
- `appolon1908-hue/codestra-production-platform`: default branch `release/production-activation`, repo
  description "Codestra production platform: Odoo 19, middleware, n8n, identity, and VICIdial
  integration" — accurately describes its role as the orchestration/policy aggregation point, not a
  runnable service.
- `telnexa` and `klyrow.com` (both `appolon1908-hue`, public): confirmed **unrelated to the Codestra
  platform** — these correspond to `codestra-provider` (10.40.0.4), a different host in the SSH mesh,
  out of this audit's confirmed scope. No further action taken on them.

## 4. Throwaway directories under /opt/codestra (sampled)

Sampled `middleware-fixture-6198-aor-fix` (contains `alembic.ini`, `app/`, `app.py`, `contracts/`,
`deploy/` — a full app checkout, not just a patch) and attempted `crm-os-cert-rbac-20260822` (referenced
in `docker ps` container names but **the directory no longer exists on disk** — the container
`codestra-rbac-kc-app-20260822` etc. were built from a working directory that has since been deleted,
meaning those exited containers are now unreproducible/unrebuildable from current disk state).

No crontab entries and no `/etc/systemd/system` or `/etc/cron.d` units reference `middleware-fixture-*`
or `crm-os-cert-*` paths — **no live scheduled job depends on the throwaway directories**, which is the
important safety check. They appear to be genuinely abandoned one-off remediation/certification attempts
(consistent with the dozens of "agent/\*-20260822" branches seen in the production-platform repo and the
equally dozens of "crm-os-cert-\*"/"rbac-\*" exited containers from the same date). Given the sheer
volume (100+ directories, 200+ exited containers, mostly dated 2026-08-22), this looks like a single very
large automated remediation/certification sweep that ran many parallel candidate branches; most were
apparently abandoned in place rather than cleaned up.

**Finding GH-05 (P3):** No safety issue found (nothing live references the throwaway dirs), but the
volume of dead directories/containers/images is a housekeeping and disk-usage concern (host is at 84%
disk use) and materially slows down any future audit or incident response by burying the handful of
directories that matter among ~100 abandoned ones. Recommend a cleanup pass *after* Phase 1 findings are
resolved (not blind deletion — some exited containers/images may still be evidence for the P0 above).

## Summary counts

- P0: 1 (GH-03)
- P1: 0
- P2: 2 (GH-01, GH-04)
- P3: 2 (GH-02, GH-05)

All SHAs, PR numbers, and digests above are non-secret identifiers copied verbatim from `git`/`gh`/
`docker inspect` output; no credential or token values are included in this report.
