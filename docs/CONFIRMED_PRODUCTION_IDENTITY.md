# Confirmed Production Identity

```text
Application Server A: 65.109.65.169
Dedicated VICIdial server: 65.21.67.207

GitHub repository:
https://github.com/appolon1908-hue/codestra-production-platform
Git remote:
https://github.com/appolon1908-hue/codestra-production-platform.git

Odoo:
crm.codestra.agency

Middleware:
api.codestra.agency

n8n:
n8n.codestra.agency

Keycloak:
auth.codestra.agency
```

## Current DNS blocker

`auth.codestra.agency` must have an A record resolving to:

```text
65.109.65.169
```

Do not treat the public Keycloak/TLS gate as passing until authoritative and public DNS resolution returns that address.

Other application construction, local testing, repository curation, middleware work, Odoo work, and non-public Keycloak testing may continue while DNS is pending.
