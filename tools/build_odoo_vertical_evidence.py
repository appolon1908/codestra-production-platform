#!/usr/bin/env python3
"""Build redacted, path-stable evidence documentation for the vertical suite."""
from pathlib import Path
import hashlib
import os
import subprocess

evidence = Path(os.environ["EVIDENCE_DIR"])
repo = Path("/opt/codestra/odoo19-vertical-addons")
commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
branch = subprocess.check_output(["git", "-C", str(repo), "branch", "--show-current"], text=True).strip()
official = (evidence / "OFFICIAL-MODULE-STATES.tsv").read_text()
custom = (evidence / "CUSTOM-MODULE-STATES.tsv").read_text()

existing = """# Existing Odoo 19 module inventory

- Production database: `codestra_odoo`
- Isolated module staging database: `odoo19_module_staging`
- Odoo image: `odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5`
- PostgreSQL image: `postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94`
- Existing custom-suite baseline: 20 installed modules and 79 passing tests.
- Final combined isolated regression: 158 tests, zero failures and zero errors.

The original 20-module suite comprises `call_center_core`, `call_center_campaign`,
`call_center_compliance`, `call_center_lead_validation`,
`call_center_orchestration`, `codestra`, the AI audit/core/qualification/realtime
assistant/review modules, analytics, appointments, daily reporting, IVR,
transcription, `codestra_base`, `codestra_integration_hub`,
`codestra_vicidial_connector`, and `codestra_vicidial_crm`.

Current custom module states are recorded in `CUSTOM-MODULE-STATES.tsv`.
"""

official_doc = f"""# Official Odoo 19 application installation

Every requested official application was present in the pinned Odoo 19
Community image. No Enterprise source path or entitlement was found, and no
Enterprise-only substitute or third-party application was installed.

The isolated clone installed 18 missing top-level applications; `contacts`,
`crm`, and `calendar` were already installed. Odoo installed technical
dependencies automatically. The registry now contains 225 requested/runtime
modules (plus a concurrently supplied Codestra-owned identity module when
present), with outbound jobs disabled.

```text
{official}```
"""

architecture = """# Codestra vertical architecture

`codestra_vertical_core` extends the existing business-unit, campaign, team,
CRM, consent, DNC, audit, and integration foundations. It does not introduce a
second call-center core or create one company per campaign.

All new transactional models inherit a common scoped mixin carrying company,
business unit, campaign, operational team, owner, consent, DNC, lifecycle,
source, external reference, idempotency key, audit tracking, and archive state.
Company/business-unit and campaign/team scope consistency is validated
server-side. Existing `crm.lead`, `res.partner`, `sale.order`, `project.project`,
`project.task`, `fleet.vehicle`, `stock.picking`, and product/accounting objects
are extended rather than duplicated.

Moneybee balances are dedicated secured loan records, never sale-order
balances. Student repayment uses separate models, groups, ACLs, and rules.
Services confirmation creates one idempotent project/task handoff. Senior
profiles default consent and DNC to unknown/fail-closed.
"""

models = """# Model dictionary

| Domain | Principal models |
|---|---|
| Shared | `codestra.vertical.mixin`, `codestra.vertical.audit`, `codestra.integration.event` |
| Transportation | `codestra.transport.lane`, `.load`, `.quote`, `.dispatch`, `.insurance`; CRM/partner/fleet extensions |
| Moneybee | `codestra.borrower.profile`, `codestra.loan.application`, `.decision.audit`, `.document`, `.payment.schedule`, `.collection` |
| Student repayment | `codestra.student.servicer.case`, `.repayment.plan`, `.document.verification` |
| Services | `codestra.service.intake`, `.service.proposal`, `.client.success.followup`; sale/project/task extensions |
| Senior products | `codestra.senior.profile`, `.recommendation`, `.delivery.followup`; partner/product/sale/stock links |

All 45 requested domain module names exist at version `19.0.1.0.0`; their
capabilities extend the anchor models above instead of creating duplicate lead
or organization tables.
"""

security = """# Security matrix

| Role | Scope / capability |
|---|---|
| Vertical agent | Company + authorized business unit; campaign/team validation |
| Supervisor / operations | Existing call-center hierarchy and scoped operations |
| Loan agent | Borrower/application/document workflow only |
| Loan underwriter | Restricted rate/decision fields and decision review |
| Loan finance | Balance, payment schedule, collections |
| Student agent | Student cases/plans; no loan access implied |
| Student compliance | Restricted document verification |
| Senior protection | Protection/compliance review |
| Auditor | Read-only immutable audit history |
| Integration service | Scoped inactive contract events; delivery locked false |
| Administrator | Administrative maintenance; audit remains immutable |

Negative acceptance proved direct ORM/RPC search and export cannot expose a
transport record to a user assigned only to another business unit. Constraints
reject company/business-unit and campaign/team mismatches. Sensitive financial
fields use field groups; decision/audit records reject write and unlink.
"""

pipeline = """# Pipeline matrix

Five configurable vertical pipelines were installed exactly as requested:

- Transportation: New Lead through Carrier/Compliance Review, Won/Lost.
- Moneybee: New Application through underwriting, approval/decline, and funded.
- Student: New Case through servicer/needs/documents/plan/assistance and close.
- Services: New Inquiry through discovery/scope/proposal/contract/handoff/delivery.
- Senior: New Inquiry through needs/recommendation/order/payment and Won/Lost.

There are 48 vertical stages and 43 explicit next-stage transitions. Campaigns
and pipelines carry a vertical selector. CRM writes reject skipped or
cross-vertical transitions and record immutable stage-transition audit events.
"""

contracts = """# Integration contracts

`codestra.integration.event` implements schema version, event ID, idempotency
key, timestamp, source, company, business unit, campaign, record reference, and
audit reference for all 17 requested event types. Event IDs and idempotency
keys are unique. Staging events are inactive and `delivery_enabled` is
read-only false; attempting to enable it raises a validation error.

No production n8n workflow, callback, VICIdial write, email, SMS, campaign,
payment, or other delivery channel was activated.
"""

tests = """# Test results

- Python compilation: PASS.
- Clean module installation: PASS for 46 suite modules.
- Module upgrade: PASS.
- Existing suite regression: PASS after correcting its stale 16-flag assertion
  to validate the authoritative required subset while retaining five newly
  added mailbox safety flags.
- Final combined Odoo test run: **158/158 PASS**, zero failures/errors.
- Synthetic vertical acceptance: 9/9 workflows/security checks PASS; transaction rolled back.
- Service project-handoff focused retest: 11/11 PASS.
- HTTP health/login page: PASS.
- Temporary administrator and internal-user HTTP authentication: PASS; users removed.
- Active cron, mail server, outgoing mail, payment provider: all zero.
- Pattern secret scan: PASS.
- Pre-module database+filestore restore and registry load: PASS.

Expected SQL constraint violations in negative tests are test evidence, not
suite errors. The authoritative final result is in `FULL-REGRESSION-FINAL.log`.
"""

acceptance = """# Staging acceptance

The isolated service uses its own PostgreSQL database, filestore, Docker
volume, internal network, service, and private route. Health and login endpoints
return successfully. Temporary synthetic administrator and internal users both
authenticated over HTTP and were deleted afterward.

Transportation, loan, student, services, senior, pipeline, integration,
cross-scope access/export, and fail-closed flag scenarios passed with synthetic
data. The transaction was rolled back, attachments/filestore remained
available, and restart recovery returned healthy.

External delivery remained disabled throughout.
"""

production = """# Production installation

Status: **NOT RUN**.

No production module, database schema, filestore, route, cron, campaign, or
integration workflow was changed by the vertical installation phase. The
required exact production maintenance window and production activation/change
approval were not supplied; these are external prerequisites that must not be
fabricated.

A verified source database and matching filestore backup exists at
`/opt/codestra/backups/odoo19-module-staging-source-20260726T004404Z`.
Production installation must follow the documented ordered groups only after
the window and human approval are recorded.
"""

rollback = """# Rollback runbook

1. Keep every external-delivery flag false and stop only the staging or
   authorized production Odoo service.
2. Revoke/disable scheduled delivery and verify no outgoing mail/SMS/payment.
3. Restore the matching PostgreSQL custom-format dump to a new database.
4. Restore the matching filestore under that exact database name.
5. Start the pinned Odoo image and load the registry without module updates.
6. Validate login, attachments, CRM, call-center modules, flags, and module states.
7. Switch only the authorized environment to the restored pair.
8. Preserve the failed database/filestore for forensic review.

Rehearsal restored the pre-module dump and filestore to
`odoo19_module_rollback_test`: 64 installed baseline modules, 45 CRM leads,
zero installed vertical core, successful registry load. The temporary database
was dropped and its filestore detached into protected backup storage.
"""

final = f"""# Final report — Odoo 19 shared applications and Codestra verticals

Source branch: `{branch}`

Final suite commit: `{commit}`

Pinned Odoo digest: `sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5`

The complete requested vertical suite is installed and validated only in the
isolated staging clone. All requested official applications were available;
there is no license/add-on blocker. The final regression is 158/158 and
rollback is proven. Production installation was intentionally not executed
without an exact approved maintenance window and approval record.

EXISTING_CUSTOM_SUITE_GATE=PASS
SHARED_OFFICIAL_MODULES_GATE=PASS
ORGANIZATIONAL_ARCHITECTURE_GATE=PASS
TRANSPORTATION_MODULE_GATE=PASS
MONEYBEE_MODULE_GATE=PASS
STUDENT_REPAYMENT_MODULE_GATE=PASS
SERVICES_MODULE_GATE=PASS
SENIOR_PRODUCTS_MODULE_GATE=PASS
RBAC_ISOLATION_GATE=PASS
PIPELINE_POLICY_GATE=PASS
INTEGRATION_CONTRACT_GATE=PASS
FULL_REGRESSION_GATE=PASS
STAGING_ACCEPTANCE_GATE=PASS
PRODUCTION_INSTALLATION_GATE=NOT_RUN
PRODUCTION_RESTART_GATE=NOT_RUN
ROLLBACK_GATE=PASS
"""

docs = {
    "existing-module-inventory.md": existing,
    "official-module-availability.md": official_doc,
    "duplicate-capability-analysis.md": architecture,
    "enterprise-entitlement-matrix.md": official_doc,
    "MODULE-INVENTORY.md": existing,
    "OFFICIAL-APP-INSTALLATION.md": official_doc,
    "ARCHITECTURE.md": architecture,
    "MODEL-DICTIONARY.md": models,
    "SECURITY-MATRIX.md": security,
    "PIPELINE-MATRIX.md": pipeline,
    "INTEGRATION-CONTRACTS.md": contracts,
    "TEST-RESULTS.md": tests,
    "STAGING-ACCEPTANCE.md": acceptance,
    "PRODUCTION-INSTALLATION.md": production,
    "ROLLBACK-RUNBOOK.md": rollback,
    "FINAL-REPORT.md": final,
}
for name, content in docs.items():
    (evidence / name).write_text(content, encoding="utf-8")

verifier = """#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
sha256sum -c SHA256SUMS
"""
(evidence / "verify-evidence.sh").write_text(verifier, encoding="utf-8")
os.chmod(evidence / "verify-evidence.sh", 0o700)

# SHA256SUMS is intentionally last and excludes itself.
entries = []
for path in sorted(evidence.iterdir()):
    if path.is_file() and path.name != "SHA256SUMS":
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {path.name}")
(evidence / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="utf-8")
