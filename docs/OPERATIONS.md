# Operations

Use the RBAC summary, event list, DLQ filter, and correlation timeline endpoints. Platform/operations roles may pause integrations and replay DLQ events; tenant admins remain tenant-scoped; auditors are read-only. All privileged changes create audit records.

Alert on readiness failure, growing queue/DLQ, circuit open, webhook error rate, Odoo/n8n latency, worker restarts, NATS/Redis/database health, disk, RAM, CPU, and certificate expiry. Never drain by deleting events: pause producers, resolve the dependency, replay bounded batches, and watch error/latency rates.

## TLS and mTLS certificate lifecycle

Middleware Platform Operations owns the timer, local leaf issuance, consumer reload, verification, and evidence. Security PKI owns CA authorization; Telephony Operations owns certificates issued and installed on the VICIdial peer. See `docs/TLS_MTLS.md` for the complete inventory.

Daily checks:

```bash
systemctl status codestra-certificate-renewal.timer
systemctl list-timers codestra-certificate-renewal.timer public-tls-monitor.timer
systemctl start public-tls-monitor.service
```

Safe private issuance test (no deployed files change):

```bash
CERTIFICATE_MANIFEST=/etc/codestra/tls/certificates.tsv \
  /usr/local/sbin/renew-private-certificate --dry-run --force middleware-private-ingress
```

After a real private renewal, verify the named containers are healthy, the served leaf matches the inventory, a request without a client certificate is rejected, and a request with the approved client identity reaches `/health` and `/ready`. Keep the `.overlap-*` copy until the observation window closes. Restore that pair and restart the same manifest targets to roll back.

For public TLS, validate the active Caddy configuration and run the endpoint monitor. Caddy renews and hot-reloads managed ACME certificates itself; do not run certbot against Caddy's storage.

### Private CA rotation

Never renew a leaf by casually replacing its CA. A CA alert requires Security PKI approval, dual-root trust deployment, old-identity proof, successor leaf rollout, new-identity proof, and a documented overlap window before old-root removal. The provisioning staging CA expiring 2026-08-25 is an active critical escalation and must follow this process.

Alert response: acknowledge the Alertmanager notification, identify whether the leaf or issuer is expiring, confirm the lifecycle timer's last result, and page Security PKI immediately for any CA alert or failed renewal inside 14 days. Never include private key content in tickets, logs, commands, or evidence.
