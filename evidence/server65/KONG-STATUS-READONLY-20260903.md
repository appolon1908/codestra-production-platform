# Kong private status read-only probe

Date: 2026-09-03
Target: `65.109.65.169`
Access: loopback Kong Admin API through `codestra-app`; `/status` GET only.

- Database reachable: `true`
- Active connections: `7`
- Waiting connections: `2`
- Writing connections: `5`
- Total handled connections: `402`
- Total requests: `2698`
- Reading connections: `0`

Kong process and database connectivity are responsive. Configuration
read-back, route authentication/authorization alignment, upstream health,
tenant/scope enforcement, and public-boundary certification remain separate
gates. No configuration endpoint was queried because it may contain secrets.

KONG_PROCESS=PASS
KONG_DATABASE_CONNECTIVITY=PASS
KONG_API_ALIGNMENT=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
