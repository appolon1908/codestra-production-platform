# Required credentials and approvals

- Independent PR reviewer and protected-branch merge authority.
- CI release-signing private/public key secrets and private registry credentials.
- Hetzner scoped infrastructure token and approved project/billing authority.
- Internal DNS and public cutover authority.
- KMS/secrets and production CA enrollment identities.
- Backup repository and DR-account credentials.
- Named network, database, telephony, security, monitoring and rollback owners.
- KVM/console recovery and named-admin key/sudo evidence.
- DIDWW account/contract signaling and media ranges.
- Maintenance windows for data and telephony migration.
- Separate TEST_SYN, human canary and AI canary packages.

Credentials must be injected through the approved secret manager and are never
accepted in Git, reports, chat or shell arguments.
