# SPEC-1 IPAM plan

All assignments below are `PROPOSED`, not allocated. A provider-side conflict
check and independent network approval are mandatory before apply. MTU remains
1400 unless end-to-end testing approves another value.

| Zone | Proposed assignments |
|---|---|
| `10.10.0.0/24` | EDGE-01 `.10`, EDGE-02 `.11`, ingress VIP `.20` |
| `10.20.0.0/24` | ODOO-APP `.10-.11`, Odoo VIP `.12`; MW-API `.20-.21`, API VIP `.22`; MW-WORKER `.30-.31`; N8N `.40-.42`; KC `.50-.51` |
| `10.30.0.0/24` | ODOO-DB `.10-.11`; CTRL-PG `.20-.22`; REDIS `.30-.32`; NATS `.40-.42` |
| `10.40.0.0/24` | Preserve source `.1/.2`; VICI-WEB `.10-.11`; DIALER `.20-.21`; DB `.30-.31`; ADAPTER `.40-.41`; proposed adapter VIP `.42` |
| `10.50.0.0/24` | AI-EDGE `.10-.11`; AI-GW `.20-.22` |
| `10.60.0.0/24` | OBS `.10-.11`; management/bastion candidate `.20` |

No new VIP uses `10.40.0.2`. DNS names follow role names under the approved
internal zone; public names remain unchanged until separate cutover approval.
DHCP is prohibited for service identities. Reverse records, forward routes and
return paths must be validated from every permitted zone pair.
