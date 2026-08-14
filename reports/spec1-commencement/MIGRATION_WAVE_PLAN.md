# Migration wave plan

1. Freeze/inventory current migration source and establish signed watermarks.
2. Approve IPAM, cost, owners, failure domains and provider accounts.
3. Apply reviewed networks, management, PKI, secrets, monitoring and backups.
4. Deploy HA PostgreSQL, Redis and NATS; certify failover and restoration.
5. Deploy Keycloak, Odoo, middleware and n8n with every production flag false.
6. Restore paired Odoo DB/filestore and other control-plane data in isolation.
7. Build the new telephony tier without carrier activation; migrate adapter
   dependencies while preserving `8443/9443/9444` on the source.
8. Deploy disabled AI infrastructure and synthetic tool/media fixtures only.
9. Run recovery, capacity and migration rehearsals with no PSTN/customer calls.
10. Deploy exact signed digests, run the 24-hour soak and TEST_SYN.
11. Seek separate network/DNS/data cutover and human-canary authorization.

Every wave has a distinct rollback point. Source servers remain intact until
post-cutover retention and rollback expiry are independently approved.
