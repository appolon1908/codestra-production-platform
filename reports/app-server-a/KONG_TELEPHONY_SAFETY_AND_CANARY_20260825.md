# Kong telephony safety and canary gate — 2026-08-25

```text
KONG_CERTIFICATION=FAIL
CADDY_CERTIFICATION=PASS
MAINTENANCE_GATE=ACTIVE
```

The global Kong maintenance gate was not changed. No call was placed, no
operator evidence was overridden, and no Caddy configuration was modified.

## Runtime inventory

| Component | Live state | Safety observation |
| --- | --- | --- |
| VICIdial | Active on private host `codestra-vicidial` | Runtime validation passes. |
| Asterisk | Active since 2026-08-16 | Authoritative channel/registration CLI is root-restricted. |
| VICIdial dialer processes | Active | Middleware production dialing and all write switches remain disabled. |
| Passive event gateway | Active; AMI connected | External delivery disabled. |
| Restricted VICIdial adapter | Active; `/health` and `/ready` return 200 | `writes_enabled=false`. |
| Middleware telephony provisioning | Healthy | Provisioning/write switches disabled. |
| Middleware VICIdial adapter | Healthy | Repeated `kill_switch_closed`; all write/read/control switches disabled. |
| Middleware PJSIP adapter | Healthy | Repeated `kill_switch_closed`; provisioning disabled. |
| WebSocket/WebRTC gateway | Healthy and ready | `websocket_connections_active=0`. |
| Callback routes | Live through Caddy/Kong | Missing authentication returns 401; maintenance remains before a valid upstream request. |

```text
ACTIVE_CALLS=UNKNOWN_AUTHORITATIVE_PROBE_DENIED
ACTIVE_CHANNELS=UNKNOWN_AUTHORITATIVE_PROBE_DENIED
SIP_REGISTRATIONS=UNKNOWN_AUTHORITATIVE_PROBE_DENIED
DIALER_ACTIVE=YES
OUTBOUND_DIALING_ENABLED=NO
WEBRTC_SESSIONS=0
TELEPHONY_PROBE=FAIL
```

The active VICIdial dialer processes are not evidence of calls by themselves.
The middleware workers continuously report `kill_switch_closed`, and the
deployed adapter reports writes disabled. SIP registrations cannot be safely
classified without the Asterisk readback.

```text
SIP_REGISTRATION_CLASSIFICATION=UNKNOWN_REQUIRES_PRIVILEGED_READBACK
TELEPHONY_ACTIVITY_SAFE=NO
```

## Probe diagnosis

```text
PROBE_COMMAND=ssh codestra-vicidial sudo -n /usr/sbin/asterisk -rx <read-only command>
PROBE_TARGET=codestra-vicidial (10.40.0.2:22), Asterisk local control socket
PROBE_EXPECTED_RESULT=successful core channel count and PJSIP registration readback
PROBE_ACTUAL_RESULT=sudo: a password is required (both commands, exit 1)
ROOT_CAUSE=deployed Server B sudo policy permits only codestra-vicidial-operator actions and does not permit direct Asterisk CLI commands
```

SSH DNS/TCP/authentication pass. Asterisk and VICIdial are active, and the
allowlisted remote operator's `validate-runtime` action reports
`VOICE_RUNTIME_VALIDATION=PASS`. The failure is specifically the mismatch
between Server A's production operator probe and Server B's least-privilege
sudo contract. Repair requires an approved, source-controlled Server B operator
action that returns sanitized call/channel/registration counts, followed by a
sudoers deployment and a corresponding Server A operator update. Broad direct
Asterisk sudo access is not recommended.

## Safety flags

The legacy `codestra-middleware-1` and the three current production runtime
containers report all canonical flags false:

```text
SEND_EVENTS=false
ENABLE_EXTERNAL_DELIVERY=false
LIVE_WRITE=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false
PRODUCTION_DIALING=false
ODOO_DELIVERY_ENABLED=false
CALLBACK_DISPATCH=false
ENABLE_VICIDIAL_WRITES=false
LIVE_CALL_CONTROL=false
GENERAL_AI_DIALING=false
LIVE_PSTN_DIALING=false
```

`CALLS_PLACED` is not a deployed runtime variable. No test call was placed by
this certification, but an authoritative zero-call count still requires the
Asterisk probe. Therefore `SAFETY_FLAGS=PASS` but activation safety remains NO.

## Network path evidence

| Path | Evidence | Result |
| --- | --- | --- |
| Middleware to telephony | Target is `edge.internal.codestra.agency:8443`; container DNS returns `gaierror`. | FAIL |
| Server A host to VICIdial | Host resolves private `10.40.0.2`; SSH TCP and authentication pass. | PASS |
| Kong/internal API to telephony gateway | Internal middleware services are healthy, but the downstream VICIdial hostname fails inside their containers. | FAIL |
| Provider to callback gateway | Public TLS verifies and unauthenticated callback request returns 401. | PASS edge/auth enforcement; application callback not exercised. |
| WebRTC | Gateway health/readiness pass and active authenticated sockets equal zero. | PASS |

The container DNS defect must be repaired in the authoritative middleware
deployment manifest, preserving the private WireGuard destination and mTLS. A
random Docker alias or staging target must not be introduced.

## Operator result and canary decision

Latest Server A operator evidence:

`/var/lib/codestra-production-operator/evidence/20260825T233745Z-1302417-status.json`

The read-only status action itself completed, but its safety state cannot pass
because the authoritative Asterisk commands return nonzero. Consequently no
maintenance-gate change is authorized and no narrow bypass was deployed.

```text
TELEPHONY_PROBE=FAIL
ACTIVE_CALLS=UNKNOWN
ACTIVE_CHANNELS=UNKNOWN
SAFETY_FLAGS=PASS
OPERATOR_ACTIVATION_SAFE=NO
NARROW_CANARY_AVAILABLE=NO_NOT_DEPLOYED_BEFORE_SAFETY
CANARY_SCOPE=NONE
CANARY_AUTH=NONE
CANARY_ROLLBACK=GLOBAL_GATE_REMAINS_UNCHANGED
MAINTENANCE_GATE_CHANGE_APPROVED=NO
CADDY_KONG_MIDDLEWARE_CANARY=BLOCKED
```

## External actions required

1. Approve and deploy a least-privilege Server B operator action providing
   sanitized Asterisk channel, call, and registration readback.
2. Reconcile Server A's production operator to consume that action and classify
   idle infrastructure registrations separately from active call channels.
3. Repair `edge.internal.codestra.agency` resolution in the authoritative
   middleware production deployment and verify mTLS from the actual containers.
4. Re-run the operator. Only if it reports zero calls/channels and activation
   safe may a source-controlled narrow Kong canary be reviewed and executed.

