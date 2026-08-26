# Kong PostgreSQL fencing request

Requested decision: select and authorize one enforceable provider-backed fence.
Supported patterns are compute power isolation, provider API isolation, network
ACL isolation, or managed database fencing.

```text
FENCING_PROVIDER=Hetzner_control_plane_API_matching_actual_primary_product
FENCE_ACTION=provider_hard_power_off_primary
VERIFY_ACTION=provider_state_off_and_private_ports_5432_22_unreachable_three_checks
UNFENCE_ACTION=manual_after_DNS_removal_and_reseed_approval
OWNER=Ralph_Appolon
CREDENTIAL_AUTHORITY=protected_Hetzner_API_secret_authority
```

**NO PROMOTION WITHOUT POSITIVE FENCE CONFIRMATION.** The promotion workflow must
call the approved fence, independently verify that the former primary cannot
serve PostgreSQL or accept writes, record `FENCE_VERIFIED=YES`, and only then
permit promotion. Any timeout, ambiguous response, unavailable credential, or
failed verification exits nonzero with the replica still read-only.

Unfencing is prohibited until the old primary is rebuilt/reseeded from the new
authority and verified as a read-only streaming standby. Rollback before
promotion removes the attempted fence; rollback after promotion follows the
same fenced promotion process in reverse.
