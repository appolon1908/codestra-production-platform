#!/usr/bin/env python3
"""Plan and transactionally apply the Server A nftables perimeter.

The program never edits SSH configuration, keys, users, ports, or services. It
reads the current sshd listener set and preserves every listener without source
restriction before adding a default-deny input policy. Live apply requires an
out-of-band console assertion and an automatic full-ruleset rollback timer.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PACKAGE = Path(__file__).resolve().parents[2] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import ContractError, atomic_write, atomic_write_json, load_json, require_executable, run_command  # noqa: E402

TABLE_NAME = "codestra_server_a"
DEFAULT_CONFIG = Path("/etc/codestra/server-a-certification/firewall.json")
DEFAULT_EVIDENCE_ROOT = Path("/opt/codestra/evidence/server-a-certification/firewall")
INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")
SSH_EFFECTIVE_KEYS = {
    "allowgroups", "allowusers", "authenticationmethods", "denygroups",
    "denyusers", "listenaddress", "passwordauthentication", "permitrootlogin",
    "port", "pubkeyauthentication", "usepam", "x11forwarding",
}


def parse_listener(local: str) -> tuple[str, int]:
    if local.startswith("[") and "]:" in local:
        host, port = local.rsplit(":", 1)
        host = host[1:-1]
    else:
        host, port = local.rsplit(":", 1)
    return host, int(port)


def current_ssh_listeners() -> list[dict[str, Any]]:
    result = run_command(["ss", "-H", "-ltnp"], timeout=20)
    listeners: list[dict[str, Any]] = []
    for raw in result.stdout.decode("utf-8", "replace").splitlines():
        if "sshd" not in raw:
            continue
        parts = raw.split()
        if len(parts) < 5:
            continue
        host, port = parse_listener(parts[3])
        listeners.append({"address": host, "port": port, "protocol": "tcp"})
    unique = sorted({(item["address"], item["port"]) for item in listeners})
    if not unique:
        raise ContractError("no current sshd TCP listener could be identified")
    return [{"address": address, "port": port, "protocol": "tcp"} for address, port in unique]


def file_metadata(path: Path) -> dict[str, Any]:
    info = path.lstat()
    record: dict[str, Any] = {
        "path": str(path), "mode": oct(info.st_mode & 0o7777), "uid": info.st_uid,
        "gid": info.st_gid, "size": info.st_size, "symlink": path.is_symlink(),
    }
    if path.is_file() and not path.is_symlink():
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return record


def current_ssh_effective_settings() -> dict[str, list[str]]:
    result = run_command(
        ["sshd", "-T", "-C", f"user=root,host={socket.gethostname()},addr=127.0.0.1"],
        timeout=30,
    )
    selected: dict[str, list[str]] = {}
    for raw in result.stdout.decode("utf-8", "replace").splitlines():
        key, separator, value = raw.partition(" ")
        if separator and key in SSH_EFFECTIVE_KEYS:
            selected.setdefault(key, []).append(value.strip())
    if not selected:
        raise ContractError("cannot determine effective sshd settings")
    return {key: sorted(values) for key, values in sorted(selected.items())}


def current_ssh_sessions() -> list[dict[str, str]]:
    result = run_command(["ss", "-H", "-tnp", "state", "established"], timeout=20)
    sessions: set[tuple[str, str]] = set()
    for raw in result.stdout.decode("utf-8", "replace").splitlines():
        if "sshd" not in raw:
            continue
        parts = raw.split()
        if len(parts) < 5:
            continue
        local = parts[3]
        peer = parts[4]
        sessions.add((local, hashlib.sha256(peer.encode("utf-8")).hexdigest()))
    return [{"local": local, "peer_sha256": peer_sha256} for local, peer_sha256 in sorted(sessions)]


def ssh_state() -> dict[str, Any]:
    paths = [Path("/etc/ssh/sshd_config")]
    paths.extend(Path(value) for value in glob.glob("/etc/ssh/sshd_config.d/*"))
    paths.extend(Path(value) for value in glob.glob("/root/.ssh/authorized_keys"))
    paths.extend(Path(value) for value in glob.glob("/home/*/.ssh/authorized_keys"))
    records = [file_metadata(path) for path in sorted(set(paths)) if path.exists()]
    return {
        "files": records,
        "effective_settings": current_ssh_effective_settings(),
        "listeners": current_ssh_listeners(),
        "active_sessions": current_ssh_sessions(),
    }


def assert_ssh_state_unchanged(before: dict[str, Any], after: dict[str, Any]) -> None:
    for field in ("files", "effective_settings", "listeners"):
        if before.get(field) != after.get(field):
            raise ContractError(f"SSH {field} changed during the transaction")
    before_sessions = {(item.get("local"), item.get("peer_sha256")) for item in before.get("active_sessions", [])}
    after_sessions = {(item.get("local"), item.get("peer_sha256")) for item in after.get("active_sessions", [])}
    if before_sessions - after_sessions:
        raise ContractError("an SSH session present at transaction start is no longer established")


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema") != "codestra.server-a-firewall.v1":
        raise ContractError("unsupported firewall contract schema")
    if config.get("target_server") != "65.109.65.169":
        raise ContractError("firewall contract target must be Server A")
    public_interface = str(config.get("public_interface", ""))
    private_interface = str(config.get("private_interface", ""))
    for field, value in (("public_interface", public_interface), ("private_interface", private_interface)):
        if not INTERFACE_RE.fullmatch(value) or value.startswith("REPLACE_"):
            raise ContractError(f"{field} must be an explicit existing interface")
        run_command(["ip", "link", "show", "dev", value], timeout=20)
    if public_interface == private_interface:
        raise ContractError("public and private firewall interfaces must differ")
    private_networks: list[str] = []
    for value in config.get("private_ipv4_subnets", []):
        network = ipaddress.ip_network(str(value), strict=True)
        if network.version != 4 or not network.is_private:
            raise ContractError("private_ipv4_subnets must contain private IPv4 CIDRs")
        private_networks.append(str(network))
    if not private_networks:
        raise ContractError("at least one private IPv4 subnet is required")
    public_tcp = sorted({int(value) for value in config.get("public_tcp_ports", [])})
    public_udp = sorted({int(value) for value in config.get("public_udp_ports", [])})
    for value in public_tcp + public_udp:
        if value < 1 or value > 65535:
            raise ContractError("public port is outside the valid range")
    if 80 not in public_tcp or 443 not in public_tcp:
        raise ContractError("public HTTP and HTTPS must remain explicitly allowed")
    urls = config.get("required_https_urls")
    if not isinstance(urls, list) or not urls:
        raise ContractError("required_https_urls must contain at least one HTTPS endpoint")
    for value in urls:
        if not isinstance(value, str) or not value.startswith("https://") or "\n" in value:
            raise ContractError("required endpoint validation URLs must use HTTPS")
    rollback_seconds = int(config.get("rollback_seconds", 180))
    if rollback_seconds < 120 or rollback_seconds > 600:
        raise ContractError("rollback_seconds must be between 120 and 600")
    return {
        "public_interface": public_interface,
        "private_interface": private_interface,
        "private_ipv4_subnets": private_networks,
        "public_tcp_ports": public_tcp,
        "public_udp_ports": public_udp,
        "required_https_urls": urls,
        "rollback_seconds": rollback_seconds,
    }


def nft_set(values: list[int]) -> str:
    return "" if not values else "{ " + ", ".join(str(value) for value in values) + " }"


def quote_nft(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def render_ssh_accept_rules(ssh_listeners: list[dict[str, Any]]) -> list[str]:
    rules: list[str] = []
    seen: set[tuple[str, int]] = set()
    for listener in ssh_listeners:
        address = str(listener["address"])
        port = int(listener["port"])
        key = (address, port)
        if key in seen:
            continue
        seen.add(key)
        comment = 'comment "preserve current sshd listener without source restriction"'
        if address in {"0.0.0.0", "::", "*"}:
            rules.append(f"    tcp dport {port} accept {comment}")
            continue
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
        family = "ip" if parsed.version == 4 else "ip6"
        rules.append(f"    {family} daddr {address} tcp dport {port} accept {comment}")
    if not rules:
        raise ContractError("no SSH listener rule could be rendered")
    return rules


def render_rules(config: dict[str, Any], ssh_listeners: list[dict[str, Any]]) -> str:
    public_tcp = config["public_tcp_ports"]
    public_udp = config["public_udp_ports"]
    lines = [
        f"table inet {TABLE_NAME} {{", "  chain input {",
        "    type filter hook input priority -50; policy drop;",
        '    iifname "lo" accept comment "loopback"',
        "    ct state established,related accept", "    ct state invalid drop",
        '    ip protocol icmp accept comment "IPv4 control traffic"',
        '    ip6 nexthdr ipv6-icmp accept comment "IPv6 control traffic"',
    ]
    lines.extend(render_ssh_accept_rules(ssh_listeners))
    private_if = quote_nft(config["private_interface"])
    for network in config["private_ipv4_subnets"]:
        lines.append(f'    iifname {private_if} ip saddr {network} accept comment "approved private service network"')
    public_if = quote_nft(config["public_interface"])
    lines.append(f'    iifname {public_if} tcp dport {nft_set(public_tcp)} accept comment "approved public TCP"')
    if public_udp:
        lines.append(f'    iifname {public_if} udp dport {nft_set(public_udp)} accept comment "approved public UDP"')
    lines.extend([
        "  }", "", "  chain forward {",
        "    type filter hook forward priority -50; policy accept;",
        "    ct state established,related accept",
        f'    iifname {public_if} ct status dnat meta l4proto tcp ct original proto-dst {nft_set(public_tcp)} accept comment "approved original public TCP mapping"',
    ])
    if public_udp:
        lines.append(f'    iifname {public_if} ct status dnat meta l4proto udp ct original proto-dst {nft_set(public_udp)} accept comment "approved original public UDP mapping"')
    lines.extend([
        f'    iifname {public_if} ct status dnat drop comment "default deny public Docker exposure"',
        f'    iifname {public_if} drop comment "default deny other public forwarding"',
        "  }", "}", "",
    ])
    return "\n".join(lines)


def snapshot_rules(path: Path) -> None:
    current = run_command(["nft", "list", "ruleset"], timeout=30).stdout
    atomic_write(path, b"flush ruleset\n" + current, mode=0o600)


def verify_urls(urls: list[str]) -> None:
    for url in urls:
        run_command([
            "curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "20",
            "--proto", "=https", "--tlsv1.2", url,
        ], timeout=30)


def schedule_rollback(snapshot: Path, seconds: int, unit: str) -> None:
    run_command([
        "systemd-run", f"--unit={unit}", f"--on-active={seconds}s", "--property=Type=oneshot",
        "/usr/sbin/nft", "-f", str(snapshot),
    ], timeout=30)


def cancel_rollback(unit: str) -> None:
    for suffix in (".timer", ".service"):
        run_command(["systemctl", "stop", unit + suffix], check=False, timeout=30)
        run_command(["systemctl", "reset-failed", unit + suffix], check=False, timeout=30)


def apply_rules(candidate: Path, snapshot: Path) -> None:
    run_command(["nft", "delete", "table", "inet", TABLE_NAME], check=False, timeout=30)
    try:
        run_command(["nft", "-f", str(candidate)], timeout=30)
    except Exception:
        run_command(["nft", "-f", str(snapshot)], timeout=30, check=False)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--apply", action="store_true")
    action.add_argument("--rollback", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        for executable in ("nft", "ss", "ip", "curl"):
            require_executable(executable)
        if args.rollback:
            if os.geteuid() != 0:
                raise ContractError("firewall rollback requires root")
            snapshot = args.rollback.resolve()
            if not snapshot.is_file() or "server-a-certification/firewall" not in str(snapshot):
                raise ContractError("rollback snapshot is not an approved Server A evidence artifact")
            run_command(["nft", "-f", str(snapshot)], timeout=30)
            print("SERVER_A_FIREWALL_ROLLBACK=PASS")
            return 0

        config = validate_config(load_json(args.config))
        before = ssh_state()
        candidate_text = render_rules(config, before["listeners"])
        args.evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        plan_path = args.evidence_root / "candidate.nft"
        atomic_write(plan_path, candidate_text.encode("utf-8"), mode=0o600)
        run_command(["nft", "--check", "-f", str(plan_path)], timeout=30)
        if args.plan:
            print(json.dumps({
                "schema": "codestra.server-a-firewall-plan.v1", "status": "PASS",
                "target_server": "65.109.65.169", "ssh_listeners_preserved": before["listeners"],
                "public_tcp_ports": config["public_tcp_ports"], "public_udp_ports": config["public_udp_ports"],
                "candidate": str(plan_path), "live_rules_changed": False,
            }, sort_keys=True, indent=2))
            return 0

        if os.geteuid() != 0:
            raise ContractError("firewall apply requires root")
        if os.environ.get("CODESTRA_OUT_OF_BAND_CONSOLE_CONFIRMED") != "YES":
            raise ContractError("out-of-band provider console must be confirmed before apply")
        if os.environ.get("CODESTRA_FIREWALL_APPLY_CONFIRM") != "APPLY_SERVER_A_DEFAULT_DENY":
            raise ContractError("typed firewall apply confirmation is missing")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        transaction = args.evidence_root / stamp
        transaction.mkdir(mode=0o700)
        candidate = transaction / "candidate.nft"
        atomic_write(candidate, candidate_text.encode("utf-8"), mode=0o600)
        snapshot = transaction / "rollback-ruleset.nft"
        snapshot_rules(snapshot)
        atomic_write_json(transaction / "ssh-before.json", before)
        unit = f"codestra-firewall-rollback-{stamp.lower()}"
        schedule_rollback(snapshot, config["rollback_seconds"], unit)
        applied = False
        try:
            apply_rules(candidate, snapshot)
            applied = True
            input_chain = run_command(["nft", "list", "chain", "inet", TABLE_NAME, "input"], timeout=30).stdout.decode("utf-8", "replace")
            if "policy drop" not in input_chain:
                raise ContractError("candidate input chain is not default deny")
            after = ssh_state()
            assert_ssh_state_unchanged(before, after)
            verify_urls(config["required_https_urls"])
            atomic_write_json(transaction / "ssh-after.json", after)
            result = {
                "schema": "codestra.server-a-firewall-result.v1", "status": "PASS", "timestamp": stamp,
                "host_ipv4_input_policy": "DROP", "host_ipv6_input_policy": "DROP",
                "docker_published_port_policy": "EXPLICIT_ALLOWLIST",
                "ssh_configuration_changed": False, "ssh_keys_changed": False,
                "ssh_listeners_changed": False, "ssh_source_restriction_changed": False,
                "rollback_test": "ARMED_AND_CANCELLED_AFTER_VALIDATION",
                "validated_https_urls": config["required_https_urls"],
            }
            atomic_write_json(transaction / "RESULT.json", result)
            cancel_rollback(unit)
            atomic_write_json(args.evidence_root / "LAST_RESULT.json", result)
            print(json.dumps(result, sort_keys=True))
            return 0
        except Exception:
            if applied:
                run_command(["nft", "-f", str(snapshot)], timeout=30, check=False)
            cancel_rollback(unit)
            raise
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SERVER_A_FIREWALL=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
