# Kong service and upstream read-only read-back

Date: 2026-09-03
Target: `65.109.65.169`
Access: loopback Kong Admin API via `codestra-app`; GET only.

## Aggregate

- Services: `20`
- Kong upstream objects: `0`
- Route targets use direct service hosts/ports rather than named Kong
  upstream objects.
- Internal service hosts include Docker service names and `10.40.0.3`;
  no public database target was observed in the service list.
- The `breero-production-api` service targets
  `scraper.internal.codestra.agency:8443` over HTTPS.

With zero Kong upstream objects, upstream health/target failover and timeout
read-back cannot be certified from the Admin API. Direct service target
reachability and route-to-contract ownership still require the approved
sanitized operator validation.

KONG_SERVICES_READ=PASS
KONG_UPSTREAM_HEALTH=FAIL
KONG_API_ALIGNMENT=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
