# Telephony network zones

| Zone | Binding and policy | Permitted use |
|---|---|---|
| Public | `65.21.67.207`, default reject | Web 80/443, approved SIP/IAX, WSS 8089, RTP 10000-20000, TURN 5349 and 49160-49199, SSH 22 |
| Private application | `10.40.0.2`, exact-source rules from `10.40.0.1` | mTLS adapters on 8443, 8444 and 9443 |
| Database | loopback only | MariaDB 3306 |
| Management | SSH plus local systemd/CLI | administration and health timers |

The public and VLAN interfaces currently share firewalld's `public` zone, but
private application ingress is separated by destination and exact-source rich
rules. Services themselves bind to `10.40.0.2`; their ports are not generally
allowlisted. This is functional policy separation, not a distinct firewalld
zone object.

```text
PUBLIC_DATABASE_ACCESS=DENIED
PUBLIC_AMI_ACCESS=DENIED
PUBLIC_ARI_ACCESS=DENIED
PUBLIC_MYSQL_ACCESS=DENIED
PUBLIC_REDIS_ACCESS=DENIED
PUBLIC_INTERNAL_API_ACCESS=DENIED
```

TCP reachability to the middleware (`65.109.65.169`), AI (`5.9.108.250`) and
web (`49.12.145.107`) servers was verified. The middleware also accepts the
dedicated root SSH identity for encrypted backup transfer. ICMP to private peer
`10.40.0.1` is blocked; this does not invalidate application connectivity.

