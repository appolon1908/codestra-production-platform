# Klyrow production mTLS certification

Captured read-only at `2026-09-13T17:34:58Z` from the Klyrow provider host
(`37.27.128.39`, private address `10.40.0.4`) and Server A's existing
restricted credential-certification interface (`10.40.0.1`). No certificate,
private key, credential, service, network, delivery flag, or DNS record was
changed.

## Certificate inventory

| Role | Subject / identity | Required name | Validity (UTC) | SHA-256 fingerprint | Result |
| --- | --- | --- | --- | --- | --- |
| Klyrow private server | `CN=klyrow-server` | `DNS:klyrow.internal.codestra.agency`, `IP:10.40.0.4` | 2026-08-17 02:54:50 through 2026-11-15 02:54:50 | `D3:A6:6D:77:FC:3B:6B:8C:64:33:B3:7B:88:04:A3:B8:DE:D8:C7:D4:BB:C3:0A:61:D8:3B:A3:52:92:81:6A:B8` | **PASS** |
| Klyrow client to Server A | `CN=klyrow-email-provider` | `URI:spiffe://codestra.internal/provider/klyrow-email-provider`, `IP:10.40.0.4` | 2026-08-19 23:17:16 through 2026-11-17 23:17:16 | `6A:58:65:27:AE:5B:7C:73:15:90:B5:AF:E0:02:55:70:DF:69:B3:16:FC:90:5C:02:6A:02:E4:32:CF:90:E5:C9` | **PASS** |
| Server A event listener | `CN=middleware-email-events.internal.codestra.agency` | `DNS:middleware-email-events.internal.codestra.agency`, `IP:10.40.0.1` | 2026-08-23 00:42:59 through 2026-11-21 00:42:59 | `ED:F3:2A:75:2D:4D:DC:43:18:7C:F3:77:73:60:24:44:E2:56:97:AF:35:76:08:CC:81:B1:1D:5C:09:E9:5D:BE` | **PASS** |

All three leaves chain to the existing Codestra provider-integration trust
hierarchy. The configured platform root is valid through
`2036-08-14T02:54:50Z`.

## Live transport verification

An authenticated connection to
`middleware-email-events.internal.codestra.agency` at `10.40.0.1:18080`
completed with:

- TLS 1.3 and `TLS_AES_128_GCM_SHA256`;
- certificate-chain verification `OK`;
- peer-name verification for
  `middleware-email-events.internal.codestra.agency`;
- the installed `klyrow-email-provider` client identity.

Server A's fixed, restricted `certify klyrow` action returned
`CERTIFIER_RESULT=PASS`. Its fail-closed checks also reported:

- `KLYROW_MTLS=PASS`;
- plaintext fallback denied;
- the new credential accepted and the old credential denied;
- both authorized tenants accepted and both cross-tenant directions denied;
- unmapped identity, disabled tenant, missing permission, caller-supplied
  tenant authority, and header spoofing denied;
- registry-database credential migration and diagnostic redaction passed.

## Certification boundary

This evidence supersedes the September 2 statement that Klyrow's private mTLS
identity was not certified. It certifies the currently installed Klyrow/Server
A transport and authorization boundary only. It does not certify the pending
application release tuple, the Server A Docker-network topology, a message
send, staging promotion, backup/restore, or rollback.

```text
KLYROW_PRODUCTION_MTLS=PASS
KLYROW_PLAINTEXT_FALLBACK=DENIED
KLYROW_OLD_CREDENTIAL=DENIED
KLYROW_CROSS_TENANT_ACCESS=DENIED
PRODUCTION_CHANGED=NO
MESSAGES_SENT=0
```
