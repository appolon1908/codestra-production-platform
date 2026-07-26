# Synthetic identity acceptance — 2026-07-26T02:47Z

## Result

A second, clearly synthetic staging request was created to continue the runtime
acceptance drill:

- Odoo request: `PRV-2026-000041`
- Employee: `MOY.2026.00007`
- Odoo user ID: `112`
- Login: `test.agent.20260726t0247z@staging.invalid`
- Business unit: Transportation and Logistics staging
- Odoo campaign: `MOY-STAGE-SYNTH`
- VICIdial candidate: `moy00007`
- SIP extension: `6198`

Extension `6198` was proven unused before reservation across VICIdial users,
phones and live agents, managed Asterisk fragments, and the loaded PJSIP
configuration. Extension `6101` was excluded.

The request was submitted, approved, and reserved. It was never marked Active.
The bounded VICIdial creation call was rejected by the supported installed
Non-Agent API, so no downstream telephony resource was created. The request
was terminated and its database-only reservations were released.

## Defects found and corrected

The drill found that a 20-character truncated name-based VICIdial identifier
collided with the previous synthetic request and that an appended suffix could
exceed the provider limit. The implementation now:

- generates an attributable business-unit/employee-number identifier;
- keeps collision suffixes inside the 20-character provider limit;
- emits an identifier compatible with the deployed adapter's safe character
  policy; and
- has a regression test for collision length.

Odoo module upgrade and tests after the correction:

```text
codestra_identity_provisioning: 21 tests
0 failed
0 errors
```

Corrected source commit:
`292d07dd4a62255a2a1b3aaa0d2c6e556ec7e2ac`

The provisioning-service mailbox lifecycle and security tests also passed
(`13 passed`) and were committed as:
`443817236cd19da45ad69ee99ce28c7903278540`.
Those tests use the explicitly non-provider-backed synthetic mail sink and are
not treated as an email runtime gate.

## VICIdial credential remediation and runtime result

The historical credential exposed by the earlier diagnostic remains encrypted
and quarantined. A minimal root-only credential reference was constructed from
the existing protected Non-Agent secret, without printing or persisting its
value outside the approved secret path.

Two installed principals passed a redacted, read-only `version` API probe.
The dedicated Non-Agent principal then reached the supported `add_user`
operation but was rejected because it lacks user-provisioning authority.
No database write was used to bypass that authorization.

Post-attempt proof:

```text
VICIdial user moy00007=absent
VICIdial phone/extension 6198=absent
VICIdial live agent moy00007=absent
managed PJSIP fragment 6198=absent
loaded PJSIP endpoint 6198=absent
telephony adapter=active
telephony adapter writes_enabled=false
external_dialing=false
```

## Controlled rollback

```text
request_state=terminated
employee_active=false
odoo_user_active=false
blocked_steps=7
extension_6198=released
reserved_identifiers_released=employee_id,keycloak_username,email,
  sip_extension,vicidial_username
historical_request_and_audit_preserved=true
```

No Keycloak identity, mailbox, VICIdial user, phone, SIP endpoint, or Agent
Desktop session was created for this second attempt, so none remained orphaned.

## Unresolved runtime authorities

- A dedicated VICIdial Non-Agent API principal with the reviewed minimum
  `add_user`, `update_user`, `add_phone`, and `update_phone` authority is not
  available.
- No provider-backed email staging sandbox/credential is configured.
- Odoo staging has no configured Keycloak-backed login flow for password setup,
  MFA completion, and Odoo login.
- The Agent Desktop staging binding remains specific to excluded endpoint
  `6101`; no `6198` session/authorization binding exists.

These are external runtime/configuration requirements. Mocks, in-memory
adapters, clean-module tests, and the successful disabled-Keycloak subtest from
the prior attempt are not used to promote a gate.

## Required gates

```text
ODOO_USER_PROVISIONING_GATE=BLOCKED
KEYCLOAK_PROVISIONING_GATE=BLOCKED
EMAIL_PROVISIONING_GATE=BLOCKED
VICIDIAL_PROVISIONING_GATE=BLOCKED
SIP_PROVISIONING_GATE=BLOCKED
AGENT_DESKTOP_AUTHORIZATION_GATE=BLOCKED
MFA_GATE=BLOCKED
CAMPAIGN_ISOLATION_GATE=BLOCKED
SUSPENSION_GATE=BLOCKED
REACTIVATION_GATE=BLOCKED
TERMINATION_GATE=BLOCKED
RECONCILIATION_GATE=BLOCKED
SYNTHETIC_END_TO_END_GATE=BLOCKED
ROLLBACK_GATE=BLOCKED
```
