# TLS and mTLS Audit

The current host runs Caddy on public 80/443 and private `10.40.0.3:8443`; Caddy is healthy and its data/config volumes support automatic certificate management. The audited control-plane live health endpoint at `10.40.0.1:8095` is plain HTTP on the private VLAN. TLS handshakes to `.1:443` and `.1:8443` did not complete, so no PASS is claimed for certificate chain, SAN, expiry, renewal, or reload.

Repository contracts reference CA, client certificate, and client key files for NATS and the VICIdial adapter; configuration is evidence of intent only. Live mTLS is BLOCKED until the middleware operator exposes the actual certificate paths and SNI without revealing private keys.
