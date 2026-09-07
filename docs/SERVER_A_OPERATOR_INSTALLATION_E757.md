# Server A operator installation package — e75783f

Status: preparation only. The protected source release is already approved;
installation remains blocked by the key fingerprint, execution window, and a
separately authorized privileged invocation.

## Fixed identities

- Protected source: `e75783fee4ea60259e3aee8e0b5ebe6eb30617dd`
- Immutable release asset: `codestra-production-platform-e75783fee4ea60259e3aee8e0b5ebe6eb30617dd.tar.gz`
- Archive SHA-256: `fc7842ab8145b2d5149256b45bbe939f9aaedd9ff31e245a388590e19d5553b1`
- Manifest SHA-256: `0124b209f34e60fcd5f1099708ccc87ad133f43282d7859f829fe032f825a458`
- Installer SHA-256: `015c9fc7f839a32f3703c92398c801299eb2a8680c1323b5c3f7095562330584`
- Launcher SHA-256: `5a00af38ab12f7b25a0a63605f186ffe1b379bdbace6b0c93eb52987f5039a70`
- Middleware image: `sha256:bca7a220b9ce50411ae67e2115507329656c4ee351333d14568af3695e3c347a`
- Change: `CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01`
- Public key: `/home/codestra-admin/operator-current.tR55n3.pub`
- Maintenance date/window: `PENDING_OWNER_SELECTION`
- Public-key SHA-256 fingerprint: `PENDING_AUTHORIZED_ROOT_READBACK`

`deployment-manifest.json` and `provenance.json` bind the archive name and
digest to the protected source and release workflow invocation
`34124572630:1`. The archive uses the `codestra/` root required by the operator.
It is not an Odoo bundle, image digest, installer digest, or historical package.

## Read-only preflight

Run these only from the root-controlled staged release after its files and
manifest have been independently reverified:

```sh
sha256sum operations/production-operator/install-server-a-operator.sh
sha256sum operations/production-operator/launch-reviewed-installation.sh
python3 tools/validate_server_a_operator_installation_record.py \
  config/server-a-operator-installation-record.json
ssh-keygen -lf /home/codestra-admin/operator-current.tR55n3.pub -E sha256
visudo -cf /etc/sudoers
operations/production-operator/validate-server-a-operator.sh
```

The fingerprint command requires an authorized administrator because the key
is root-owned mode `0600`. Do not copy, replace, regenerate, or loosen the key.

## Prepared privileged action

After the missing fingerprint, its owner confirmation, and the maintenance
date are recorded, the zero-argument launcher is the only prepared invocation:

```sh
sudo ./operations/production-operator/launch-reviewed-installation.sh
```

The launcher validates the complete record and installer checksum, verifies the
existing key fingerprint, and supplies exactly these six installer inputs in
preserve mode: public-key path, protected source, image digest, change ID,
maintenance date, and control-plane archive SHA-256.

## Rollback

Before changing a target, the installer records whether it was absent or makes
a private root-only byte-and-metadata backup. Any failure attempts every safe
restore, preserves the original nonzero status, and retains private recovery
evidence if restoration is incomplete. The existing reviewed sudoers file is
validated before mutation and is neither replaced nor included in the changed
file ledger. A PASS requires the post-install validator and installed checksum
readback; release existence alone is not installation evidence.

No command in this document authorizes installation, service restart, database
change, traffic activation, credential work, queue activation, or delivery.
