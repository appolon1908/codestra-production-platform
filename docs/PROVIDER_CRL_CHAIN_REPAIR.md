# Provider mTLS CRL chain repair

Nginx checks revocation across the client certificate chain. A bundle containing only the provider intermediate's CRL cannot establish the revocation status of the intermediate itself. The TLS handshake may complete but nginx rejects the request with HTTP 400. See the [nginx ssl_crl contract](https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_crl).

Keep client verification, subject checks, TLS versions, trust anchors, and existing revoked serials intact. The deployed `client.crl` must contain both the provider-issued CRL and the root-issued CRL. Do not fix this failure by removing `ssl_crl` or disabling certificate verification.

`operations/tls/provider_crl_bundle.py` prepares new candidate files using the existing root signer. It pins the selected root certificate by SHA-256, verifies key ownership and permissions, verifies CRL signatures and time validity, preserves root revocations during renewal, preserves the provider CRL, and refuses overwriting candidate files. It changes no runtime configuration and exports no signing key. It requires the operational Python cryptography package.

First root CRL issuance requires the explicit `--initialize-root-crl` option after the operator verifies that no prior root CRL or root-revocation registry exists. If one exists, supply it with `--previous-root-crl`; never bootstrap a replacement empty list. This is root-signer maintenance and does not replace or rotate the CA.

Before installation:
1. Preserve the current public CRL bundle and nginx configuration in protected rollback storage.
2. Verify the intermediate certificate chain with OpenSSL against the selected root.
3. Verify the production client with `openssl verify -crl_check_all` against the candidate bundle.
4. Verify an already-revoked test certificate remains rejected.
5. Install only the public root CRL and bundle, run `nginx -t`, and reload nginx.
6. Check an authenticated read-only health endpoint and rejection without a client certificate.

Restore the old bundle and reload nginx if validation fails. Keep private signing material on its existing authority host; transfer only public CRLs. Retain the root CRL as durable revocation state. Renew before the earlier issuer's nextUpdate; root CRLs are capped at 30 days and provider CRLs have their own expiry. Offline root custody remains a separate responsibility.
