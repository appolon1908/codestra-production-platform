# Deployment

1. Back up `/opt/middleware`, `/opt/codestra/compose`, n8n workflow exports, reverse-proxy configuration, and current container/firewall inventories.
2. Generate independent random values from `config/control-plane.env.example` into `/etc/codestra/secrets/control-plane.env`; set mode 0600.
3. Run `docker compose -f deploy/control-plane/compose.yaml config`, build, and start.
4. Verify `http://127.0.0.1:8096/health`, `/ready`, authenticated `/api/v1/ops/summary`, and `/metrics`.
5. Keep `CONTROL_PLANE_OUTBOUND_ENABLED=false` until Odoo adapter and n8n workflow URLs/credentials are approved and synthetic acceptance passes.

Rollback stops the additive Compose project and restores its named volume if needed. It does not alter the existing `10.40.0.1:8095` ingress or production Odoo/n8n containers.
