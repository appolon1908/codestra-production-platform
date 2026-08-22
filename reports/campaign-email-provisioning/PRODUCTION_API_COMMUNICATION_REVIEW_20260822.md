# Production API and communication review

Date: 2026-08-22
Branch: `agent/first-mail-production-hardening-20260822`
Base: protected `release/production-activation` at `3b3b65371962b1ce915f44a73c07a90fe1431c1d`

## Release decision

The source candidate is suitable for protected review and isolated deployment.
Internet mail activation remains fail-closed until the one-domain DNS, ownership,
provider readback, canary, and independent approval gates pass.

## API strength

- Canonical Keycloak issuer and an existing authoritative subject are mandatory;
  the mailbox adapter cannot create an untracked user.
- Agent grants are restricted to `codestra-email-agent`; grant and revocation are
  read back and known mail-administrator roles fail the operation.
- Keycloak, Klyrow, and Odoo service calls use tenant-bound short-lived tokens,
  correlation IDs, idempotency keys, a dedicated mTLS client, redirect denial,
  response-size limits, and pinned private endpoints.
- Klyrow provisioning reads back the exact mailbox identity, exact non-catch-all
  inbound route, and exact sender authorization before activation.
- Odoo receives an explicit allowlist only. Provider credentials, Keycloak
  secrets, SMTP passwords, tokens, roles, and scopes are excluded.
- Failures always persist a safe terminal state even when provider compensation
  fails. Odoo receives PROVISIONING, ACTIVE, or safe PROVISIONING_FAILED state.
- Exact replay returns the same mailbox; altered replay is denied. Sender checks
  bind tenant, agent, campaign, and exact From address.

## Communication path

```text
Odoo authority -> Kong -> middleware reservation
  -> existing Keycloak subject + least privilege/readback
  -> Klyrow identity -> exact inbound route -> exact sender/readback
  -> non-external outbound validation -> ACTIVE
  -> secret-free Odoo projection/readback

Postal controlled inbound -> exact active recipient
  -> tenant/campaign/agent/mailbox binding
  -> MIME/size/filename policy -> mandatory malware scan
  -> tenant-isolated clean storage or quarantine
  -> Odoo projection/readback with Message-ID/thread/correlation preservation
```

Unknown recipients have no route. Attachments are never projected before a
clean scan, executable extensions and unsupported MIME types are denied, and
infected or scanner-error results are quarantined without delivery.

## Remaining production gates

- `codestra.co` still has two conflicting DMARC records, Zoho MX, no certified
  DKIM selector for Klyrow, and PTR/HELO alignment to `mail.klyrow.com` rather
  than the proposed domain.
- TEST_SYN still lacks an authoritative campaign membership and campaign UUID.
- The protected Klyrow runtime identity/route/sender API has not been exercised
  with destination readback because deployment authority is unavailable.
- No controlled internal send/inbound canary or suspension/reactivation runtime
  test has run against the real provider.
- CI, container/dependency scans, and legitimate independent PR approval must
  pass on the final commit. This author does not self-approve.
- The rebuilt pinned Python 3.12.13/Debian 13 image has no secret findings, but
  Trivy still reports 3 critical and 52 high OS/dependency occurrences. It is
  not eligible for production promotion until those findings are remediated or
  independently reviewed under the protected vulnerability process.

No domain, mailbox, user, catch-all, route, sender, or external delivery was
activated as part of this source hardening.
