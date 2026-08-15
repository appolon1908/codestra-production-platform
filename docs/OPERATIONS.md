# Operations

Use the RBAC summary, event list, DLQ filter, and correlation timeline endpoints. Platform/operations roles may pause integrations and replay DLQ events; tenant admins remain tenant-scoped; auditors are read-only. All privileged changes create audit records.

Alert on readiness failure, growing queue/DLQ, circuit open, webhook error rate, Odoo/n8n latency, worker restarts, NATS/Redis/database health, disk, RAM, CPU, and certificate expiry. Never drain by deleting events: pause producers, resolve the dependency, replay bounded batches, and watch error/latency rates.
