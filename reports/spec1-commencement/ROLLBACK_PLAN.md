# Rollback plan

Infrastructure apply uses exact saved plans, state backups and provider rollback
procedures. Application deploys use immutable previous digests and atomic
traffic switches. Data migrations are additive/backward-compatible until
cutover acceptance. Telephony source remains intact and carrier routing remains
unchanged until separate authorization.

On failure: keep/restore all global flags false; stop publishers/workers as
needed; preserve inbox/outbox/spool/audit; restore prior signed digests and valid
certificates; revert firewall/DNS/LB through reviewed plans; verify no call was
interrupted; reconcile counts; publish incident evidence. Never delete events,
audit records, historical calls or filestore orphans.
