# CODEX UPDATE — GITHUB, DOMAINS, DNS, AND INITIAL COMMIT

## Confirmed facts

- Application Server A: `65.109.65.169`
- Dedicated VICIdial server: `65.21.67.207`
- GitHub owner: `appolon1908-hue`
- GitHub repository: `codestra-production-platform`
- Git remote: `https://github.com/appolon1908-hue/codestra-production-platform.git`
- Odoo: `crm.codestra.agency`
- Middleware: `api.codestra.agency`
- n8n: `n8n.codestra.agency`
- Keycloak: `auth.codestra.co`

GitHub authentication is active and `origin` points to the repository.

The working tree contains extensive uncommitted content. Do not blindly run `git add -A` and do not push until secret and artifact curation is complete.

## Required action

Continue implementation, but first create a safe repository baseline and initial commit.

### 1. Verify repository identity

Run and record:

```bash
git rev-parse --show-toplevel
git remote -v
git status --short --branch
git branch --show-current
git config --get user.name
git config --get user.email
```

Verify `origin` is exactly the confirmed GitHub repository.

Do not overwrite existing user identity settings unless they are missing.

### 2. Preserve the current working tree

Before curation:

- Create a timestamped inventory of every untracked and modified path.
- Record file sizes and types.
- Do not delete or reset files.
- Do not use `git clean`, `git reset --hard`, or destructive checkout commands.
- Create a local evidence directory outside Git for the inventory when appropriate.
- Back up configuration files before editing them.

Generate:

```text
reports/github/PRE_INITIAL_COMMIT_STATUS.md
reports/github/WORKING_TREE_INVENTORY.csv
reports/github/UNTRACKED_LARGE_FILES.csv
```

### 3. Secret and sensitive-artifact review

Inspect the complete working tree, including untracked files, for:

- `.env` and secret environment files
- Passwords
- API tokens
- GitHub tokens
- Keycloak secrets
- Database credentials
- Redis credentials
- n8n encryption keys
- SMTP/SMS/provider credentials
- SIP and carrier credentials
- SSH private keys
- TLS private keys
- Database dumps
- Odoo filestore content
- Backups
- Recordings
- Customer exports
- Lead lists
- Logs containing authorization headers or customer data
- Generated evidence that contains secrets
- Node, Python, build, cache, and vendor directories
- Large binary artifacts
- Container volumes

Use repository-native scanners when present. Use an installed secret scanner when available. Also perform targeted filename and content checks.

Never print discovered secret values into reports. Record only:

- Path
- Secret category
- Detection method
- Redacted fingerprint or hash
- Required remediation
- Whether the file is ignored, removed from staging, rotated, or moved to protected storage

Generate:

```text
reports/github/SECRET_REVIEW.md
reports/github/SENSITIVE_ARTIFACT_REVIEW.md
reports/github/IGNORE_POLICY.md
```

### 4. Curate `.gitignore`

Preserve existing rules and add only missing rules.

At minimum, protect:

```text
.env
.env.*
!.env.example
config/application-server-a.env
config/*.secret.env
*.pem
*.key
*.p12
*.pfx
*.sql
*.sql.gz
*.dump
*.backup
*.tar
*.tar.gz
*.tgz
*.zip
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
node_modules/
dist/
build/
.cache/
logs/
*.log
evidence/private/
reports/private/
backups/
recordings/
filestore/
data/
volumes/
```

Do not ignore source migrations, workflow exports, test fixtures explicitly designed for Git, or required configuration examples.

### 5. Separate source from runtime state

Git should contain:

- Source code
- Odoo addons
- Middleware code
- n8n workflow exports without credentials
- Tests
- Migrations
- Schemas
- Deployment definitions
- Reverse-proxy templates
- Monitoring configuration
- `.env.example` files
- Documentation
- Safe scripts
- Safe evidence templates

Git must not contain:

- Live secret files
- Runtime database data
- Redis data
- Odoo filestore
- n8n runtime database
- Keycloak runtime database
- Call recordings
- Customer lead lists
- Database backups
- Provider credentials
- Generated container volumes

### 6. Curated staging

Stage logical groups, not the whole working tree at once.

Recommended order:

1. Repository governance and documentation
2. Configuration examples
3. Odoo source and tests
4. Middleware source and tests
5. n8n workflow exports and tests
6. Infrastructure and deployment
7. Monitoring
8. CI workflows

After each group:

```bash
git diff --cached --stat
git diff --cached --check
git diff --cached
```

Inspect every staged path.

Do not stage any file that has not been classified.

### 7. Initial commit requirements

The initial commit may proceed only when:

- Secret review is complete.
- Sensitive runtime artifacts are excluded.
- `.gitignore` is validated.
- Staged diff is reviewed.
- Tests that can run locally have been executed.
- Repository contains no known live secret.
- Generated reports redact values.
- Deployment and configuration examples contain placeholders or secret references only.

Use a clear commit such as:

```text
chore: establish curated production platform baseline
```

Then record the commit SHA.

### 8. Push requirements

Before push:

```bash
git status --short
git log -1 --oneline
git remote -v
```

Push the curated branch:

```text
release/production-activation
```

Do not force-push.

If the remote repository is empty and policy permits, create the branch and push it normally. Do not push directly to a protected default branch unless repository policy explicitly requires it.

Generate:

```text
reports/github/INITIAL_COMMIT_REPORT.md
reports/github/PUSH_REPORT.md
reports/github/DEPLOYMENT_PROVENANCE.md
```

## Domain and reverse-proxy updates

Use:

```text
crm.codestra.agency   → Odoo
api.codestra.agency   → Middleware
n8n.codestra.agency   → n8n
auth.codestra.co      → Keycloak
```

Validate each hostname independently.

Do not request or renew a public certificate for a hostname until it resolves to the intended server and port 80/443 routing is correct.

### Required DNS check

For Keycloak:

```bash
dig +short auth.codestra.co A
getent ahostsv4 auth.codestra.co
```

Expected address:

```text
65.109.65.169
```

When it does not resolve correctly:

- Record `KEYCLOAK_PUBLIC_DNS_GATE=BLOCKED`.
- Keep public Keycloak activation and public certificate issuance blocked.
- Continue local/private Keycloak configuration and tests where safe.
- Do not fake `/etc/hosts` as production DNS proof.
- Do not report the public authentication gate as passing.

### Reverse-proxy safety

- Preserve existing routes.
- Validate configuration before reload.
- Back up current configuration.
- Use atomic deployment or symlink/versioned configuration where practical.
- Reload rather than restart when supported.
- Verify Odoo, middleware, n8n, and Keycloak routes separately.
- Enforce TLS, secure headers, request limits, and WebSocket routing where required.
- Restrict administrative and metrics endpoints.

## Configuration file update

The protected local file:

```text
config/application-server-a.env
```

must remain ignored and mode `0600`.

Update only these non-secret values:

```env
GITHUB_REPOSITORY=https://github.com/appolon1908-hue/codestra-production-platform.git
ODOO_DOMAIN=crm.codestra.agency
MIDDLEWARE_DOMAIN=api.codestra.agency
N8N_DOMAIN=n8n.codestra.agency
KEYCLOAK_DOMAIN=auth.codestra.co
```

Preserve all secret-file references and all unknown existing values.

## Completion output

Print:

```text
GITHUB_REMOTE_VERIFIED=
WORKING_TREE_INVENTORIED=
SECRET_REVIEW=
SENSITIVE_ARTIFACT_REVIEW=
GITIGNORE_VALIDATED=
INITIAL_COMMIT_SHA=
PUSH_STATUS=
DEPLOYMENT_BRANCH=

ODOO_DOMAIN=
MIDDLEWARE_DOMAIN=
N8N_DOMAIN=
KEYCLOAK_DOMAIN=
KEYCLOAK_DNS_RESULT=
KEYCLOAK_PUBLIC_DNS_GATE=

SECRET_FILES_PRESERVED=
PROTECTED_ENV_MODE=
CRITICAL_BLOCKERS=
EVIDENCE_DIRECTORY=
```

Begin now. Do not delete uncommitted work. Do not push until the curated initial commit gates pass.
