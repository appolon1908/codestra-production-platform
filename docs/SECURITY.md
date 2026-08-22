# Communications security

The service is loopback-bound behind existing private ingress. Tenant scope is derived from tenant credentials or an authorized operator request; reads and writes filter by tenant. Provider callbacks require channel-specific bearer keys, HMAC-SHA256, fresh timestamps, unique event IDs, and constant-time comparison. Secrets stay in environment-owned files, never URLs, payload metadata, Git, or logs.

The provider adapter permits only `10.40.0.2`, localhost, or loopback. Production needs explicit authorization and separate channel credentials. Containers run UID 10001, read-only, capabilities dropped, with no-new-privileges and bounded request size. Existing mTLS, rate limits, key rotation, dependency/secret scans, secure headers, and destination allowlists remain mandatory.
