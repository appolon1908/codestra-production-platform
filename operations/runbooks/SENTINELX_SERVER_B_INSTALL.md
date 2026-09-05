# SentinelX Server B installation runbook

## Scope and stop conditions

This runbook covers only SentinelX on `static` (`65.21.67.207`, private
`10.40.0.2`). It does not authorize Ralph account creation, telephony
activation, firewall/SSH changes, distribution upgrades, or changes to
Asterisk, VICIdial, MariaDB, and Codestra provisioning services.

Use an existing authorized root login. Do not expand `codestra-admin` sudo or
bypass `/usr/local/sbin/codestra-vicidial-operator`. Stop if an existing
`/etc/sentinelx`, `/opt/sentinelx-cloud-core`, `sentinelx` user, or
`sentinelx-cloud-core.service` is found; preserve and review its host ID,
identity, policy, code commit, unit, ownership, and sudoers before proceeding.

## Root preflight and immutable evidence

Run these read-only checks first and retain sanitized output:

```bash
hostname
cat /etc/os-release
id
ip -brief address
systemctl status sentinelx-cloud-core.service --no-pager || true
find /etc/sentinelx /opt/sentinelx-cloud-core -maxdepth 2 -ls 2>/dev/null || true
getent passwd sentinelx || true
test -e /etc/sudoers.d/sentinelx && visudo -c -f /etc/sudoers.d/sentinelx
command -v python3.11 git curl systemctl
python3.11 -c 'import pip, venv; print("pip+venv OK")'
```

Create the protected review directory and download the official installer:

```bash
install -d -m 0700 /root/sentinelx-install
curl --proto '=https' --tlsv1.2 -fSL \
  https://get.sentinelx.app/install.sh \
  -o /root/sentinelx-install/install.sh
bash -n /root/sentinelx-install/install.sh
sha256sum /root/sentinelx-install/install.sh
```

The reviewed 2026-09-05 bytes have SHA-256
`56f5da769567a471ccf798fa11105f747738f26ee48d0d106922922e56d3acb9`.
A different hash requires a fresh line-by-line review. A matching hash proves
only byte equality with the reviewed download, not publisher authenticity.

The reviewed installer requires root, Linux x86_64/aarch64, `curl`, `git`,
working systemd, and Python >=3.11 with `pip` and `venv`. It creates user
`sentinelx`, clones the core, creates an editable virtualenv installation,
downloads an enrollment helper from the installer repository's mutable `main`,
creates/retains identity and policy files, writes a systemd unit, and enables
and starts it. Without `SENTINELX_SKIP_SUDO=1` it offers the unsafe rule
`sentinelx ALL=(ALL) NOPASSWD: ALL`. The unit intentionally omits
`NoNewPrivileges=true`. The installer deletes an existing install directory,
but reuses existing host ID/config/identity, which is why the existing-install
stop condition is mandatory.

Pin the reviewed core commit for installation:
`d6b33822b61e7fccf39547d5cce8add8bc7021f9` (version `0.11.14`). Revalidate
the enrollment helper fetched during installation against the reviewed source
before accepting enrollment; the upstream installer does not provide a ref
override for that helper.

## Restricted policy before enrollment

Install the repository policy before executing the installer. The policy uses
an empty command allowlist because core `0.11.14` runs commands using
`bash -lc` and authorizes them by raw string prefix; non-empty prefixes do not
provide a safe exact-command boundary. It exposes only a sanitized health file
and makes all upload/script staging unwritable to `sentinelx`.

```bash
install -d -o root -g root -m 0500 /var/empty/sentinelx-disabled
install -d -o root -g root -m 0755 /etc/sentinelx
install -d -o root -g root -m 0755 /var/lib/sentinelx/evidence
install -o root -g root -m 0644 \
  server-b-read-only-config.yaml /etc/sentinelx/config.yaml
{
  printf 'hostname='; hostname
  printf 'kernel='; uname -srmo
  printf 'uptime='; uptime
  printf 'memory='; free -h | awk 'NR==2 {print $2 "/" $3 "/" $7}'
  printf 'rootfs='; df -hP / | awk 'NR==2 {print $2 "/" $3 "/" $4 "/" $5}'
} > /var/lib/sentinelx/evidence/health.txt
chown root:root /var/lib/sentinelx/evidence/health.txt
chmod 0444 /var/lib/sentinelx/evidence/health.txt
```

Validate the schema using the pinned core checkout before connection:

```bash
PYTHONPATH=/opt/sentinelx-cloud-core/src \
  /opt/sentinelx-cloud-core/.venv/bin/python -c \
  'from pathlib import Path; from sentinelx_core.policy import Policy; p=Policy.from_file(Path("/etc/sentinelx/config.yaml")); assert not p.allowed_commands and not p.services and not any(x.access == "rw" for x in p.file_ops_paths)'
```

## Install and owner enrollment

Run in an interactive authorized root terminal, using the reviewed file:

```bash
SENTINELX_SKIP_SUDO=1 \
SENTINELX_ENROLL_MODE=paste \
SENTINELX_CORE_REF=d6b33822b61e7fccf39547d5cce8add8bc7021f9 \
  bash /root/sentinelx-install/install.sh
```

Show the installer-provided official enrollment URL to the owner. The owner
must paste the token directly into that terminal. Never place a token in chat,
logs, files, shell arguments, environment variables, or Git. If the owner has
not completed this, stop as `BLOCKED_OWNER_ENROLLMENT` without deleting the
installation.

## Verification (no telephony mutation)

Verify local installation, runtime, and account enrollment independently:

```bash
systemctl is-active sentinelx-cloud-core.service
systemctl is-enabled sentinelx-cloud-core.service
systemctl show -p User -p Group -p MainPID sentinelx-cloud-core.service
sudo -n -l -U sentinelx
git -C /opt/sentinelx-cloud-core rev-parse HEAD
```

From the owner's dashboard, verify the exact host ID and label, authenticated
online state, and a fresh successful read of only the sanitized health file.
Then test and record rejection of: `exec`, `script_run`, `upload_file`, `edit`,
a read of `/etc/sentinelx/identity.json`, and a write to the allowed health
path. Confirm no `/etc/sudoers.d/sentinelx` exists. Finally compare the
read-only `codestra-vicidial-operator status` output with the preflight:
Asterisk/VICIdial/adapters must remain active and no business-write gate may
change. Do not restart any telephony service to perform this verification.
