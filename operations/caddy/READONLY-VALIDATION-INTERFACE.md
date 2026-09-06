# Caddy exact-command read-only validation interface

Status: proposed for independent review; not installed by this change.

## Purpose

The production operator account cannot read `/etc/caddy` or `/run/caddy`, and
must not receive a shell or broad sudo. Add one forced-command action named
`validate-caddy` after independent review and protected release.

The action must run as root with no caller-controlled arguments and may perform
only these fixed reads:

1. `/usr/bin/caddy validate --config /etc/caddy/Caddyfile`
2. `/usr/bin/systemctl is-active caddy.service`
3. TLS handshakes to the fixed loopback/public listeners and configured names
   extracted by Caddy itself from the validated config.
4. A sanitized Caddy route summary containing host matchers, path matchers,
   upstream addresses, timeout values, WebSocket capability, mTLS policy
   presence, response-header names, and access-log filter field names.

The action must never return environment variables, raw request headers,
header values, credentials, certificate private keys, secret file contents,
arbitrary config snippets, or unrestricted paths. It must fail closed unless
the access-log filter deletes `Authorization`, `Apikey`, and `X-Api-Key`, and
removes API-key query parameters.

## Required controls

- Add exactly `validate-caddy` to the forced-command allowlist and exact sudoers
  command list; do not add wildcards.
- Reject extra arguments and all SSH forwarding/TTY/subsystem requests.
- Emit a root-owned mode-0600 sanitized JSON evidence record.
- Pin and verify the validator checksum in the protected operator installer.
- Unit-test command rejection, secret redaction, config-validation failure,
  inactive service, TLS failure, missing Kong upstream, missing WebSocket
  route, and missing credential-redaction filters.
- Installation requires protected-branch merge and an independently approved
  production environment deployment.
