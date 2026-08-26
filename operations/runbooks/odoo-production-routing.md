# Odoo production routing and feature authority

The browser path is `crm.codestra.agency` through host Caddy and the private
upstream gateway to Odoo ports 8069 and 8072. It does not traverse Kong. The
`/reseller/` boundary terminates at the OIDC gateway before Odoo.

Private middleware integration uses `odoo.internal.codestra.agency` through the
internal Caddy allowlist. Only POST `/api/v1/integration/results`, POST
`/codestra/api/v1/call-events`, and GET/HEAD `/web/health` are routable, and only
from `10.254.41.0/28`. Other paths return 404; other source networks return 403.

Kong `/v1/crm` is a distinct API boundary through the service-auth adapter. It
does not expose the Odoo browser, realtime, database selector, or private
integration endpoints.

Production feature policy is owned by Ralph Appolon. Callback synchronization
is required and enabled. Broad production callbacks, n8n production workflows,
transfers, WebRTC production routes, VICIdial writes, live calls/email/SMS, and
external dialing are intentionally disabled. Activating any disabled feature
requires an exact Git revision, independent approval, maintenance window,
rollback evidence, and an updated runtime-lock fingerprint.

Odoo 8069/8072 and PostgreSQL 5432 remain private. Configured proxies replace
forwarded identity headers at their trust boundaries; authorization and cookie
headers are not included in access-log configuration.
