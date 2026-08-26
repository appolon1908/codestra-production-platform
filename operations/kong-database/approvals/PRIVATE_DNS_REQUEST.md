# Private database DNS request

Requested authority: `kong-db.internal.codestra.agency`

```text
PRIVATE_ONLY=YES
PUBLIC_A_RECORD=NONE
PUBLIC_AAAA_RECORD=NONE
DNS_BACKEND=dual_private_CoreDNS
DNS_OWNER=Ralph_Appolon
TTL=30_SECONDS
INITIAL_TARGET=10.40.0.1
PRIMARY_DNS_NODE=10.40.0.1
SECONDARY_DNS_NODE=10.40.0.4
PROMOTION_UPDATE_METHOD=HA_workflow_only_after_positive_fence_confirmation
ROLLBACK_UPDATE_METHOD=HA_workflow_only_after_writer_fencing
```

Only the approved HA promotion workflow may mutate this record. Initial creation
must point to the current primary private address. Promotion mutation occurs only
after positive fencing confirmation. Rollback restores the last authoritative
target only after preventing dual writers.

Acceptance: absent from public recursive DNS; resolvable from Kong, primary and
replica private networks; exact target and TTL read back; mutation credentials
restricted to the DNS owner/HA workflow. This request does not create DNS.
