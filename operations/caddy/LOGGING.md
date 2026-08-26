# Logging boundaries and data handling

Boundaries are public API, internal mTLS, WebSocket, identity, Odoo, n8n, provider callbacks, monitoring, and public web. The host map assigns every hostname. JSON access logs retain host, method, URI/path, status, duration, source address, upstream fields, and response X-Kong-Request-Id where Kong returns it.

Authorization, proxy authorization, API-key, cookie, and set-cookie fields are filtered on sensitive API boundaries. Query API keys are deleted. Client X-Correlation-ID is contextual only and never replaces the trusted Kong request ID. Rotation is daily, compressed, 30 days, and bounded at 100 MiB.
