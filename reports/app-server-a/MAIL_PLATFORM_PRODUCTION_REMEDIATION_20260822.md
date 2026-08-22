# Mail platform production remediation — 2026-08-22

## Activated components

- Stalwart 0.16.18 exited bootstrap mode on the isolated `mail.test` plane.
- HTTPS/JMAP, IMAPS, and SMTP submission listeners are active with TLS 1.3.
- Canonical Keycloak OIDC directory is configured with issuer
  `https://auth.codestra.co/realms/codestra` and audience
  `codestra-mail-stalwart`.
- OIDC acceptance passed for the TEST_SYN agent and standalone user.
- Disabled-user token issuance was denied; wrong-audience and wrong-issuer
  access tokens were denied by Stalwart.
- Three TEST_SYN user accounts and one TEST_SYN shared account exist in
  Stalwart. No customer account was created.
- Distinct, revocable Stalwart app passwords were created for protocol
  canaries and stored only under `/etc/codestra/secrets/mail-platform`.
- An internal TEST_SYN message and reply were delivered between `mail.test`
  mailboxes. IMAP preserved `Message-ID`, `In-Reply-To`, `References`, and the
  correlation ID.
- The canonical mail API is deployed as `codestra/mail-api:20260822` and is
  healthy. It independently validates Keycloak signature, issuer, audience,
  tenant, role, and endpoint scope.
- Kong routes `api.codestra.co/api/v1/mail*` to the mail API and applies request
  size, rate, and correlation controls. Missing authentication is denied by the
  upstream API. The Kong `openid-connect` plugin could not be activated because
  the running gateway has no Enterprise plugin license; authentication remains
  fail-closed in the private upstream.
- The registry now writes an idempotent transactional outbox record with every
  new message command. Replay does not create another message or outbox record.
- Six n8n mail workflows were imported inactive. They validate canonical event
  envelopes and contain no credentials. They remain inactive until the adapter
  and callback endpoints are certified.
- The production Odoo `codestra_mail_inbox` module binding was repaired by
  adding `/mnt/shared-inbox-addons` to the configured add-on path. Odoo restarted
  healthy and now loads the conversation, inbound event, and team models.

## Canary evidence

- OIDC valid TEST_SYN agent: HTTP 200 on JMAP session.
- OIDC valid TEST_SYN standalone user: HTTP 200 on JMAP session.
- Wrong audience: HTTP 401.
- Wrong issuer: HTTP 401.
- Disabled TEST_SYN supervisor: Keycloak `invalid_grant`; account was restored.
- IMAPS mailbox listing: PASS.
- SMTP submission with STARTTLS: PASS.
- Internal receive: PASS.
- Internal reply/thread headers: PASS.
- Mail API missing auth: HTTP 401.
- Mail API wrong tenant: HTTP 403.
- Kong valid scoped request: HTTP 200.
- Registry/API tests: 14 passed.
- Mail API image HIGH/CRITICAL vulnerabilities: 0.
- Scoped source/deployment Gitleaks findings: 0.

## Backup and restore

The post-remediation registry and both Stalwart volumes were archived under
`/opt/codestra/mail-platform-backup-20260822-runtime-cZPykb`. All SHA-256 checks
passed. The registry integrity check returned `ok`. A separate container booted
from restored Stalwart volumes and returned HTTP 200 before the temporary
container was removed. The backup archives are retained.

## Production gates deliberately retained

- `mail.codestra.co` still resolves to `49.12.145.107`, while this runtime is on
  `65.109.65.169`. No authorized shell or DNS control was available for the
  former host. Public TLS and protocol exposure cannot be promoted safely.
- `_dmarc.codestra.co` still publishes two conflicting records. No registrar
  credential was available; no DNS mutation was attempted.
- Production Odoo and middleware contain no authoritative campaign rows for the
  blocked human-mail domains. No blocked domain was activated.
- The n8n workflows, Odoo outbound transport, inbound adapter, and Klyrow bridge
  remain disabled until their authenticated runtime callbacks are implemented
  and tested together.
- The Stalwart account manager is available, but a full standalone webmail UI
  has not been deployed.
- Independent review and protected merge are still required.

## Safety result

No customer email was sent. Two messages were sent only between reserved
`mail.test` TEST_SYN mailboxes. No public DNS was changed, no customer identity
was touched, and no unassigned domain was activated.
