# Campaign email provisioning evidence

Date: 2026-08-22

The normalized schema, exclusive reservation, idempotent workflow, fail-closed rollback, exact sender authorization, exact inbound routing, Keycloak least-privilege contract, and secret-free Odoo projections are implemented in protected source. No live mailbox, route, sender, shared address, or catch-all was created.

Live read-only inventory found 105 Odoo campaigns, five active employees, and zero rows in `call_center_campaign_agent_rel`. Consequently the current expected mailbox count is zero. Proposed brand mappings were not activated: exact Odoo campaign identity is absent for most brand labels, while the COD and MBL families are inactive and still lack complete DKIM/PTR/HELO/TLS and controlled inbound/outbound validation evidence.

```text
CAMPAIGN_COUNT=105
CAMPAIGN_DOMAIN_MAPPINGS=0_ACTIVE
VERIFIED_CAMPAIGN_DOMAINS=0
AGENTS_DISCOVERED=5
AGENT_MAILBOXES_EXPECTED=0
AGENT_MAILBOXES_CREATED=0
AGENT_MAILBOXES_ALREADY_EXISTED=0
EMAIL_ADDRESS_CONFLICTS=0_LIVE
PROVISIONING_FAILURES=0_LIVE
KEYCLOAK_IDENTITIES_CREATED=0
KLYROW_IDENTITIES_CREATED=0
INBOUND_ROUTES_CREATED=0
OUTBOUND_SENDERS_AUTHORIZED=0
SENDING_VALIDATION=UNIT_PASS_LIVE_NOT_RUN
RECEIVING_VALIDATION=UNIT_PASS_LIVE_NOT_RUN
TENANT_ISOLATION=UNIT_PASS
CAMPAIGN_ISOLATION=UNIT_PASS
AGENT_ISOLATION=UNIT_PASS
CATCH_ALL_CREATED=NO
PASSWORDS_PRINTED=NO
CREDENTIALS_PRINTED=NO
LIVE_EMAILS_SENT=0
FINAL_STATUS=BLOCKED_DOMAIN_AND_ADAPTER_VERIFICATION
BLOCKERS=approved exact campaign mappings; full DNS and mail-flow gates; protected Keycloak/Klyrow/Odoo adapters; independent review
```
