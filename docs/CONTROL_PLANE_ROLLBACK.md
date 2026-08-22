# Control-plane rollback

Stop the outbox dispatcher and reconciliation remediation first. Keep desired state and the immutable ledger. Disable adapter writes and all delivery flags. Switch mapping reads back to the read-only legacy projection using the protected release configuration, restore the exact prior image digest, and verify Odoo/VICIdial read-back. Do not drop the `control_plane` schema or delete events during rollback. Any unexpectedly dialable campaign is disabled immediately through the approved adapter and classified as a security-boundary failure.
