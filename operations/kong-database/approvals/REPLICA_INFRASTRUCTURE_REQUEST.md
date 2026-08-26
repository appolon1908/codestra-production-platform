# Independent Kong PostgreSQL replica request

Requested decision: allocate and approve a host outside the primary physical
failure domain.

Minimum: PostgreSQL 17.11 support; 4 vCPU; 8 GiB RAM; 150 GiB persistent SSD/NVMe
with expansion path; private primary connectivity; TLS identity; monitoring and
off-host backup egress; provider/network fencing; no public PostgreSQL listener.

```text
REPLICA_HOST=codestra-provider
PRIVATE_IP=10.40.0.4
PRIVATE_CIDR=10.40.0.4/32
PROVIDER=Hetzner
REGION=provider_inventory_readback_required
FAILURE_DOMAIN=separate_bare_metal_host_same_provider_and_private_VLAN
CPU=4_vCPU_reserved
RAM=16_GiB_reserved
STORAGE=200_GiB_persistent_SSD_reserved
NETWORK_PATH=private_VLAN_10.40.0.0/24
TLS_IDENTITY=kong-db-replica.internal.codestra.agency
FENCING_INTERFACE=Hetzner_control_plane_API_matching_actual_primary_product
PUBLIC_DB_PORTS=0
```

Acceptance commands after allocation (never include credentials):

```bash
hostnamectl
nproc
free -h
df -hT
ip -brief address
getent hosts kong-db.internal.codestra.agency
ss -lnt
openssl s_client -connect <private-primary>:5432 -starttls postgres -verify_return_error
pg_isready -h <private-primary> -p 5432
```

Then verify `pg_is_in_recovery()=true`, read-only mode, streaming WAL receiver,
active physical slot, private-only reachability, certificate SAN/expiry, and
independent failure-domain evidence. Allocation is rejected if co-located with
the primary or lacking enforceable fencing.
