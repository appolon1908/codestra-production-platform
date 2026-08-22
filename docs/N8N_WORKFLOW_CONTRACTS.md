# n8n mapping workflow contracts

`scripts/build_mapping_workflows.py` generates 15 small, inactive workflows. Each validates schema version 1 and all envelope identity/version fields, preserves correlation and idempotency values, calls only Kong/middleware adapter routes, and posts an explicit `RESULT` through Kong. Results are `EXECUTED_NOT_VERIFIED`; n8n never marks an entity synchronized.

n8n workflow static data and direct application/VICIdial SQL are prohibited as mapping authorities. Retry, idempotency, versions, and mappings live in middleware PostgreSQL.
