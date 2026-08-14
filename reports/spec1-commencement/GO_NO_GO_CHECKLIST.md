# Go/no-go checklist

- [ ] Infrastructure/cost/owner approval
- [ ] Six-zone IPAM and default-deny plan approved
- [ ] IaC plan independently reviewed; no unapproved billable apply
- [ ] Management, console, PKI, secrets, backups and monitoring certified
- [ ] HA data/event tiers pass failover and restore
- [ ] Exact protected images, SBOM, scans, provenance and signatures verified
- [ ] Paired Odoo and all component restores pass in isolation
- [ ] Telephony ports/carrier dependencies reconciled without source disruption
- [ ] Staging isolation, recovery, reconciliation and capacity tests pass
- [ ] 24-hour exact-runtime soak passes with at least 280 samples
- [ ] TEST_SYN creates one effective test record and zero calls
- [ ] Human canary package complete and independently authorized
- [ ] AI remains disabled pending separate canary package
- [ ] Limited rollout policy defines countries, campaigns, modes, caller IDs,
      operators, concurrency, CPM, daily ceilings, stop rules and rollback owner

Current decision: `NO_GO_BLOCKED_EXTERNAL_INFRASTRUCTURE`.
