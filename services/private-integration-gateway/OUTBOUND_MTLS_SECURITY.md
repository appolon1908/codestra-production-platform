# Outbound middleware mTLS security invariant

The private integration gateway may forward governed provider events only to the exact reviewed HTTPS middleware URL with a hostname-verifying TLS 1.2-or-newer context and the configured client certificate identity.

The transport must reject every HTTP redirect before reusing any of the following on another origin:

- the outbound client certificate;
- the bearer service credential;
- the event HMAC signature;
- the event, tenant, correlation, or reconciliation headers.

A 3xx response is therefore handled as an unverified downstream result and cannot authorize delivery. The event remains within the durable retry/reconciliation state machine. Forwarding remains disabled in the committed production Compose contract until the exact downstream URL, CA, client certificate, client key, protected topology, and positive mTLS transaction evidence are separately approved.

This document records a source invariant only. It does not contain credentials, enable provider delivery, activate forwarding, or authorize a production rollout.
