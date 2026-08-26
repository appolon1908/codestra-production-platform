# Kong PostgreSQL operations

This directory is the source authority for Kong database backup, isolated restore
rehearsal, operational metrics, and alerting. Deploy the scripts to
`/usr/local/sbin`, units to `/etc/systemd/system`, and the rule file to the
production Prometheus rule directory through the reviewed platform release.

## Recovery objectives

- Daily encrypted logical backup, RPO 24 hours.
- Retention: 14 daily, 8 weekly, and 12 monthly snapshots.
- Independent encrypted Restic object storage copy on every successful run.
- Monthly isolated restore rehearsal; current measured logical restore RTO is
  recorded in root-only evidence under `/var/lib/codestra-kong-database/evidence`.
- No backup or restore listener is published.

The current single-node PostgreSQL deployment does not provide PITR or HA. Do
not claim those controls until a second failure domain, private TLS replication,
fencing authority, and a tested promotion workflow are approved and deployed.

## Failover runbook (approval required)

Owner: production platform on-call and database owner.

Trigger: confirmed primary loss or corruption after application and host checks.

1. Freeze Kong configuration mutations and declare an incident.
2. Fence the failed primary at the compute/network layer. Promotion is forbidden
   until fencing is independently confirmed.
3. Confirm the approved replica is streaming, its replay lag is within the RPO,
   and its last received/replayed LSN is consistent.
4. Promote using the HA manager's reviewed promotion command; never start a
   second independent writable database.
5. Change the stable private database authority (managed endpoint or HA virtual
   name), not individual Kong containers.
6. Verify Kong datastore health, Admin API topology counts, auth, rate limiting,
   request IDs, and proxy traffic.
7. Rebuild the former primary as a replica before it may rejoin.

Rollback means fencing the failed promotion target, selecting the authoritative
timeline, and following the same controlled promotion process. Target RTO is 15
minutes; final RPO depends on the approved synchronous/asynchronous replication
policy. No credentials belong in this runbook.

## Mutation governance

The Admin API remains loopback/private. Normal mutations flow from Git review to
validated reconciliation. Emergency Admin API changes require an incident/change
record and a same-day source reconciliation. Drift detection is read-only and
must never automatically delete an unknown production object.
