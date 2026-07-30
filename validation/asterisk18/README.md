# Off-host Asterisk 18 AMI/TLS validation harness

This directory is a CI-only, disposable denial and rollback test environment. It
must run only on a GitHub-hosted Ubuntu runner or another separately approved
ephemeral host. It has no deployment path and passing it authorizes no Server B
change.

The harness builds Asterisk 18.26.4 from the upstream, SHA-256-verified release
archive on a digest-pinned Debian base. At runtime its Docker network is
`internal`, all published ports bind to runner loopback, all Linux capabilities
are dropped, and no Docker socket, production configuration, key, credential,
database, trunk, endpoint, or telephone number is present.

Synthetic identity: `codestra_event_ro_test`. TLS hostname:
`asterisk-ami.test.invalid`. A random AMI secret and a short-lived test PKI are
generated inside each job and deleted during unconditional cleanup.

## Approved local commands

These commands are for an approved disposable validation host only:

```bash
python3 -m pip install pytest pyyaml
validation/asterisk18/scripts/start-harness.sh
validation/asterisk18/scripts/wait-for-health.sh
python3 -m pytest -q validation/asterisk18/tests
validation/asterisk18/scripts/collect-sanitized-evidence.sh
validation/asterisk18/scripts/stop-harness.sh
```

The tests never originate a real call. Write attempts use only nonexistent
synthetic channels, queues, contexts, and extensions. The container has no
external route, SIP module, endpoint, or trunk.

## Configuration-equivalence boundary

Equivalence means only the relevant effective model: Asterisk major version 18,
AMI over verified TLS, and a manager identity with required event/read classes
and `write = none`. It does not copy or infer any production value. Exact Server
B configuration reconciliation remains blocked for the next separately
authorized phase.
