# Backup and restore certification

Result: **FAIL**

The authoritative component inventory is `PRODUCTION-DATABASE-MANIFEST.yaml`. Its validator fails closed if a required store is omitted or if PASS is claimed without successful isolated restores and off-host copies.

Existing scheduled automation covers Middleware, Odoo, n8n, and Keycloak PostgreSQL dumps plus the Odoo/n8n volumes and an encrypted off-host transfer. It does not yet prove current coverage and isolated recovery for Kong, Caddy PKI state, OpenBao Raft state, or the protected release authority. Runtime execution evidence is also absent for every listed component. Timer presence and source implementation are not restore proof.

No restore may target production. OpenBao recovery remains subject to the approved security-owner custody ceremony.

RPO: FAIL — not measured for every required component.
RTO: FAIL — not measured through complete isolated restores.
