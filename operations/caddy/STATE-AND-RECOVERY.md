# Protected state, retention, and recovery

/var/lib/caddy contains ACME accounts, public and internal certificates, private keys, OCSP/cache metadata, locks, and the local PKI. Explicit mTLS material under /etc/caddy/private, /etc/caddy/secrets, and /etc/codestra/pki/middleware-private-ingress is also required to reconstruct the edge.

Private keys and ACME material are critical secret state. Certificates and issuance metadata are regenerable but operationally valuable. Backups are GPG-encrypted atomically, mode 0600, checksummed, manifested, retained locally for 14 daily copies, and copied encrypted to the independent codestra-vicidial backup host. Weekly (8) and monthly (12) retention is delegated to that host's protected lifecycle.

Backup-age thresholds are 24 and 48 hours. Restore tooling refuses an existing destination, verifies checksum and permissions, and verifies the internal CA keypair. Live restore requires an approved outage change; rehearsals remain isolated.

Central log shipping is not installed on this host and remains an external infrastructure dependency.
