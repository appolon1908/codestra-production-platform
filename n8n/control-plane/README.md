# Governed control-plane workflows

These are production catalog records, not active workflow imports. Middleware-validated events are the only input. Workflow credentials live in n8n credential storage, deployments require review, and all workflows remain inactive until their dependency, synthetic, consent, rollback, and owner-approval gates pass. Existing production workflows under `/opt/codestra/n8n-workflows` remain authoritative and were not replaced.

Naming is `CP-<number>-<SYSTEM>-<PURPOSE>-V<version>`. Development, staging, and production use separate n8n projects/databases. Export JSON after every approved change, validate it for credential material, commit it, import inactive, run synthetic tests, and activate explicitly. Roll back by deactivating the new revision and reactivating the last approved export. Failures route to `CP-90-STANDARD-ERROR-V1` and middleware DLQ.
