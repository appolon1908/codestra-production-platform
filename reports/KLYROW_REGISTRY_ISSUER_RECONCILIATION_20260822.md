# Klyrow registry issuer reconciliation

Date: 2026-08-22

The Provider Klyrow gateway resolves application credentials through the
Server A identity-certification endpoint. Credential lookup is keyed by
issuer, service, and a one-way credential hash.

The resolver correctly used the canonical Keycloak issuer
`https://auth.codestra.co/realms/codestra`, while the seven Klyrow registry
rows and the bounded registry controller still used the retired
`https://auth.codestra.agency/realms/codestra` value. Consequently, valid
credentials were returned as opaque `403 not_found` responses.

The production repair:

- backed up the registry table before mutation;
- migrated only Klyrow rows to the canonical issuer in one transaction;
- updated both bounded rotation controllers to use the canonical issuer;
- activated the already-approved target credential on Server A;
- disabled the historical credential after cutover;
- preserved automatic rollback and the fail-closed mutation freeze;
- sent no email, SMS, or PSTN traffic.

Post-repair certification passed credential authorization, historical
credential denial, mTLS, plaintext denial, tenant isolation, permission
enforcement, spoofed-header denial, registry least privilege, and secret
redaction checks. The Provider gateway remains in safe mode with its
production delivery gate unapproved.
