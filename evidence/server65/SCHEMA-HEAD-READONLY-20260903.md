# Production database schema-head read-only probe

Date: 2026-09-03
Target: `65.109.65.169` primary PostgreSQL
Access: read-only SQL against production database metadata; no writes.

| Database | Migration metadata |
|---|---|
| `codestra_middleware` | Alembic head `0054_campaign_actions` |
| `codestra_middleware_appolon` | No `alembic_version` table |
| `control_plane` | No `alembic_version` table |
| `email_reseller` | No `alembic_version` table |
| `codestra_n8n` | No `alembic_version` table |
| `codestra_odoo` | No `alembic_version` table |
| `beyvra_email` | Migration metadata `20260819_01` |

Several production databases have no detectable migration-head metadata. Their
schema identity and one-shot migration/rollback compatibility cannot be proven
from the approved read-only path.

SCHEMA_HEADS=FAIL
ONE_SHOT_MIGRATIONS=FAIL
DATABASES=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
