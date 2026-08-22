# Control-plane runbook

1. Confirm all live-delivery flags are false and capture repository SHA/image digest/database snapshot.
2. Apply migrations with the owner role; verify the runtime role is `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`.
3. Import Odoo campaigns without activation and attach Odoo IDs as `campaign_target` rows.
4. Import legacy mappings as shadow evidence. Read destinations; never infer actual state from acceptance status.
5. Start dispatcher and targeted reconciler with adapter writes disabled.
6. Require zero unexplained shadow mismatches before cutover.
7. Run only `TEST_SYN`; replay the command, submit a stale result, simulate destination failure, and restart isolated workers.
8. Enable canonical reads, leaving legacy tables read-only. Monitor pending, failed, drift, dead letters, adapter errors, stale rejects, and idempotency conflicts.

Never use a force-synced operation. Persistent retryable failures enter dead letter after five attempts. Validation, authorization, collision, stale-version, and payload-conflict failures are non-retryable.
