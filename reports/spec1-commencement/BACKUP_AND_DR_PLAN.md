# Backup and disaster-recovery plan

- Preserve restic snapshot `98a338a0`, paired Odoo backup identity, 83 orphans
  and the 1,110-event quarantine unchanged.
- Create encrypted application-consistent backups for Odoo DB/filestore,
  middleware/Keycloak/n8n PostgreSQL, VICIdial MariaDB/configuration, adapter
  spool, NATS JetStream and configuration for Redis rebuild.
- Maintain local recovery, off-server immutable retention and a separate DR
  account/zone. Keys must not share the protected data failure domain.
- Validate checksums and restore in carrier-isolated, outbound-denied networks.
- Initial acceptance objectives: Odoo RTO no worse than the measured `00:08:41`
  during rehearsal; component RPO/RTO must be approved after dataset sizing.
- Quarterly full restore and monthly sampled restore; every material schema,
  storage or encryption change invalidates prior acceptance.
