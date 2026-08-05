# Firewall policy

The active nftables/firewalld input chain accepts established traffic and
loopback, dispatches zone policy, then rejects unmatched traffic with
`admin-prohibited`.

| Port | Protocol | Source | Destination | Service | Owner | Purpose | Scope |
|---:|---|---|---|---|---|---|---|
| 22 | TCP | approved administrators | 65.21.67.207 | SSH | Infrastructure | administration | Public |
| 80,443 | TCP | public | 65.21.67.207 | Apache | Web/VICIdial | user interface | Public |
| 5060 | UDP | approved SIP ecosystem | 65.21.67.207 | Asterisk | Telephony | SIP | Public |
| 4569 | UDP | approved IAX ecosystem | 65.21.67.207 | Asterisk | Telephony | IAX | Public |
| 8089 | TCP | approved WebRTC endpoints | 65.21.67.207 | Asterisk HTTPS/WSS | Telephony | secure WebSocket; ARI disabled | Public |
| 10000-20000 | UDP | approved call peers | 65.21.67.207 | Asterisk RTP | Telephony | media | Public |
| 5349 | TCP | approved WebRTC endpoints | 65.21.67.207 | TURN | Telephony | TURN TLS | Public |
| 49160-49199 | UDP | approved WebRTC endpoints | 65.21.67.207 | TURN | Telephony | relay media | Public |
| 8443,8444,9443 | TCP | 10.40.0.1/32 | 10.40.0.2 | private adapters | Middleware/Telephony | mTLS integration | Private |
| 3306 | TCP | loopback only | 127.0.0.1 | MariaDB | Telephony | VICIdial database | Database |
| 5038 | TCP | loopback only | 127.0.0.1 | AMI | Telephony | passive events | Management |

8088 is bound by Asterisk but absent from the allow chain. ARI is configured
`enabled=no`; registered HTTP URIs are only status, Prometheus metrics and
WebSocket. Direct self-connect tests to the host's own public address traverse
local routing and therefore do not prove external exposure; the authoritative
control is the nftables allow chain.

