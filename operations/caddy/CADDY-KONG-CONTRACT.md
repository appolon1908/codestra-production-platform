# Caddy–Kong contract

Public TLS terminates at host Caddy. Caddy sends canonical API traffic to `127.0.0.1:18101`, the internal upstream-gateway Caddy, which forwards to Kong on its private network. Internal HTTP is intentional at this trusted boundary; public plaintext is unavailable and HTTP port 80 redirects to HTTPS. Kong may trust forwarded scheme only from the edge networks. Client-supplied correlation IDs are contextual; `X-Kong-Request-Id` is the canonical gateway identity.

The realtime paths `/ws/agent`, `/api/v1/realtime/sessions`, `/healthz`, `/readyz`, and `/version` on the Codestra API hosts use the separately approved gateway at `127.0.0.1:18102`. This exception is explicit and tested. Breero remains direct mTLS. Authentication is enforced by Kong or the endpoint-specific Caddy mTLS/basic-auth boundary documented in `HOST-OWNERSHIP.tsv`.
