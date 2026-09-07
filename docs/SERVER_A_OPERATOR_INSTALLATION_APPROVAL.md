# Server A operator installation approval

Reference release `462c12e9957c3e6a9d92fe94a5019cd29d09d777` proved the repaired
installer source and supplies the currently proposed image digest and change
identifier. It is not the identity of the modified installer in this change.

The canonical record is
`config/server-a-operator-installation-record.json`. It intentionally remains
`incomplete` until the new protected release exists and an owner records:

- the root-readable existing operator public-key fingerprint and approval;
- the new protected commit, archive, manifest, and installer hashes;
- reconciliation of the image digest and change ID against that release;
- an explicitly approved maintenance date; and
- the SHA-256 of the approved control-plane archive.

The control-plane value cannot be a release-package or operator checksum. A
date is never derived from the current day or an older installed tuple. Each
value may cite a separate authoritative approval.

After protected merge, publish a new immutable protected release. Reviewers
must reconcile the record to that exact release in a separate protected change
before setting `status` to `approved`. Validate it with:

```sh
python3 tools/validate_server_a_operator_installation_record.py \
  config/server-a-operator-installation-record.json
```

The committed draft is checked with `--allow-incomplete`. The launcher takes
no arguments and cannot run an incomplete record. Owner-managed bootstrap must
authorize only the exact root-controlled launcher; it must not add a shell,
arbitrary path or command, Docker-group access, Model B access, or unrestricted
sudo.

Installation success is not production activation or certification. After an
authorized installation, run `validate-server-a-operator.sh` and read-only
operator checks. Report database certification, source lock, and production
readiness from their own evidence. Do not enable workloads, traffic, calls,
email, SMS, or delivery flags as part of installation.
