# Server A default-deny firewall transaction

`server-a-firewall.py` owns only the additive `inet codestra_server_a` table.
It does not enable UFW, edit OpenSSH, alter users or keys, reload `sshd`, or
restrict existing SSH sources. The live listener set is discovered read-only
and every current SSH TCP port is admitted without a source filter before the
input chain's default-drop policy is installed.

A live apply is rejected unless:

- the target is `65.109.65.169`;
- the public/private interfaces and approved ports are explicit;
- `nft --check` passes;
- the Hetzner out-of-band console is confirmed;
- the typed confirmation is present;
- a complete ruleset rollback is scheduled with `systemd-run`;
- SSH file metadata, checksums, and listeners match before and after;
- every required HTTPS endpoint remains reachable.

The host-side Codex mission must also run an independent external IPv4/IPv6
port scan. A successful local transaction alone cannot prove that no unexpected
public port is reachable from the Internet.
