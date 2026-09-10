#!/usr/bin/env python3
"""Passive Linux seccomp incident evidence. Never repairs or certifies a host.

Uses only the standard library. Prints JSON; does not open the Docker socket,
install filters, execute in containers, read environment variables from processes,
change sysctls, install packages, or modify the protected operator. Exit 0 means
collection finished, NOT that restore or deployment is safe. Exit 2 means a
requested evidence file or host-identity check failed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import selectors
import stat
import subprocess
import time
from pathlib import Path

LIMIT = 2 * 1024 * 1024
SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
CONFIG_KEYS = {"CONFIG_SECCOMP", "CONFIG_SECCOMP_FILTER", "CONFIG_BPF",
               "CONFIG_BPF_SYSCALL", "CONFIG_BPF_JIT", "CONFIG_BPF_JIT_ALWAYS_ON"}
PACKAGE_NAMES = ("docker-ce", "docker-ce-cli", "docker.io", "containerd.io",
                 "containerd", "runc", "libseccomp2", "linux-generic",
                 "linux-image-generic", "linux-generic-hwe-22.04")
COMMANDS = {
    "packages": ("dpkg-query", "-W", "-f=${binary:Package}\\t${Version}\\t${Status}\\n",
                 *PACKAGE_NAMES, "linux-image-*"),
    "candidates": ("apt-cache", "policy", *PACKAGE_NAMES),
    "kernel_log": ("journalctl", "--dmesg", "--boot=0", "--no-pager",
                   "--output=cat", "--lines=500"),
}


def read_text(path: Path, limit: int = LIMIT) -> dict:
    """Read a bounded regular/proc file without following the final symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return {"status": "UNAVAILABLE", "reason": "not_regular_file"}
            data = stream.read(limit + 1)
        return {"status": "TRUNCATED" if len(data) > limit else "READ",
                "text": data[:limit].decode("utf-8", errors="replace")}
    except OSError as exc:
        return {"status": "UNAVAILABLE", "errno": exc.errno}


def run_readonly(name: str, timeout: float = 5.0, limit: int = LIMIT) -> dict:
    """Only named fixed commands; bounded output, time and clean child environment."""
    argv = COMMANDS[name]
    executable = None
    for directory in SAFE_PATH.split(":"):
        candidate = Path(directory) / argv[0]
        try:
            info = candidate.stat()
        except OSError:
            continue
        if (stat.S_ISREG(info.st_mode) and info.st_uid == 0
                and not info.st_mode & 0o022 and os.access(candidate, os.X_OK)):
            executable = str(candidate)
            break
    if executable is None:
        return {"status": "UNAVAILABLE", "reason": "trusted_binary_not_found"}
    try:
        with subprocess.Popen(
            [executable, *argv[1:]], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": SAFE_PATH, "LC_ALL": "C", "HOME": "/nonexistent",
                 "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"},
        ) as child:
            buffers = {"stdout": bytearray(), "stderr": bytearray()}
            status = "COMPLETED"
            end = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                for stream, label in ((child.stdout, "stdout"), (child.stderr, "stderr")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, label)
                while selector.get_map():
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        status = "TIMEOUT"
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        room = limit - sum(map(len, buffers.values()))
                        buffers[key.data].extend(data[:max(room, 0)])
                        if len(data) > room:
                            status = "TRUNCATED"
                            break
                    if status != "COMPLETED":
                        break
            if status != "COMPLETED":
                child.kill()
            try:
                returncode = child.wait(timeout=max(0.1, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                returncode = child.wait()
                status = "TIMEOUT"
            return {"status": status, "returncode": returncode,
                    **{k: bytes(v).decode("utf-8", errors="replace") for k, v in buffers.items()}}
    except OSError as exc:
        return {"status": "UNAVAILABLE", "errno": exc.errno}


def parse_fields(text: str, keys: set[str], separator: str = ":") -> dict:
    result = {}
    for line in text.splitlines():
        key, found, value = line.partition(separator)
        if found and key.strip() in keys:
            result[key.strip()] = value.strip().strip('"')
    return result


def summarize_vmalloc(text: str) -> dict:
    """Report labeled allocation lower bounds, not global BPF JIT accounting."""
    result = {"bpf_labeled_bytes": 0, "bpf_labeled_regions": 0,
              "module_alloc_labeled_bytes": 0, "module_alloc_labeled_regions": 0}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        size = int(parts[1])
        # A region can have both labels. Do not add these categories together.
        for category, matched in (("bpf", "bpf" in line.lower()),
                                  ("module_alloc", "module_alloc" in line)):
            if matched:
                result[f"{category}_labeled_bytes"] += size
                result[f"{category}_labeled_regions"] += 1
    result["interpretation"] = (
        "Labels may be absent; categories can overlap. Not bpf_jit_current, not "
        "unique seccomp filters, not free executable space; zero does not exclude exhaustion."
    )
    return result


def summarize_processes(proc: Path = Path("/proc"), limit: int = 4096) -> dict:
    result = {"examined": 0, "unreadable_or_exited": 0,
              "filter_mode_processes": 0, "sum_reported_filter_references": 0,
              "max_reported_filters_per_process": 0, "runtime_processes": []}
    try:
        pids = sorted((p for p in proc.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
    except OSError as exc:
        return {"status": "UNAVAILABLE", "errno": exc.errno}
    result["truncated"] = len(pids) > limit
    for pid in pids[:limit]:
        item = read_text(pid / "status", 32768)
        if item["status"] != "READ":
            result["unreadable_or_exited"] += 1
            continue
        fields = parse_fields(item["text"], {"Name", "Seccomp", "Seccomp_filters"})
        result["examined"] += 1
        if fields.get("Seccomp") == "2":
            result["filter_mode_processes"] += 1
        count = fields.get("Seccomp_filters", "")
        if count.isdigit():
            result["sum_reported_filter_references"] += int(count)
            result["max_reported_filters_per_process"] = max(
                result["max_reported_filters_per_process"], int(count))
        if fields.get("Name") in {"dockerd", "containerd", "runc", "containerd-shim"}:
            # Record identity only: never cmdline, environ, container config, or credentials.
            try:
                executable = os.readlink(pid / "exe")
            except OSError:
                executable = None
            result["runtime_processes"].append(
                {"pid": int(pid.name), "name": fields["Name"], "executable": executable})
    result["status"] = "PARTIAL" if result["truncated"] or result["unreadable_or_exited"] else "READ"
    result["interpretation"] = "Process references can share filters; not a unique allocation count."
    return result


def classify_error(text: str) -> dict:
    seccomp = bool(re.search(r"(?:loading|install(?:ing|ation)?|init).*seccomp|seccomp.*filter", text, re.I))
    errno_524 = bool(re.search(r"\berrno\s*[:=]?\s*524\b", text, re.I))
    return {"seccomp_filter_error_reported": seccomp, "errno_524_reported": errno_524,
            "classification": "SECCOMP_FILTER_INSTALLATION_ERRNO_524_REPORTED"
            if seccomp and errno_524 else "NOT_CLASSIFIED",
            "bpf_jit_exhaustion": "NOT_ESTABLISHED",
            "kernel_runtime_incompatibility": "NOT_ESTABLISHED"}


def inspect_evidence(path: Path | None) -> dict:
    if path is None:
        return {"status": "NOT_REQUESTED"}
    item = read_text(path)
    if item["status"] != "READ":
        return {k: v for k, v in item.items() if k != "text"}
    try:
        value = json.loads(item["text"])
    except (ValueError, RecursionError):
        return {"status": "INVALID_JSON"}
    if not isinstance(value, dict):
        return {"status": "INVALID_JSON_OBJECT"}
    # Hash the original bytes, including encoding. No secret-bearing values emitted.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return {"status": "UNAVAILABLE", "reason": "not_regular_file"}
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT or raw.decode("utf-8", errors="replace") != item["text"]:
            return {"status": "CHANGED_DURING_READ"}
    except OSError as exc:
        return {"status": "UNAVAILABLE", "errno": exc.errno}
    return {"status": "READ", "sha256": hashlib.sha256(raw).hexdigest(),
            "origin": "SUPPLIED_FILE_NOT_AUTHENTICATED_BY_COLLECTOR",
            **classify_error(item["text"])}


def summarize_packages(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] == "install ok installed":
            rows.append({"package": parts[0], "version": parts[1]})
    return rows


def command_collection_gap(name: str, item: dict, summary: list | dict) -> str | None:
    """Keep command completion separate from usable collection, without raw stderr."""
    if item["status"] != "COMPLETED":
        return "command_incomplete"
    stderr = item.get("stderr", "").strip()
    # journalctl may exit zero with only accessible messages (or none). Treat
    # every diagnostic conservatively, including unrecognized access warnings.
    if name == "kernel_log" and stderr:
        return "journal_diagnostics_present"
    if item.get("returncode") == 0:
        return None
    if name == "packages" and item.get("returncode") == 1 and summary and stderr:
        # Docker package families are alternatives. dpkg-query still prints
        # installed rows but exits 1 for absent requested packages. LC_ALL=C is
        # fixed by run_readonly; tolerate only those exact diagnostics and args.
        requested = {*PACKAGE_NAMES, "linux-image-*"}
        missing = [re.fullmatch(r"dpkg-query: no packages found matching (\S+)", line)
                   for line in stderr.splitlines()]
        if all(match and match[1] in requested for match in missing):
            return None
    return "command_failed"


def summarize_candidates(text: str) -> dict:
    rows, current = {}, None
    for line in text.splitlines():
        match = re.fullmatch(r"([a-z0-9][a-z0-9+.:~_-]*):", line)
        if match:
            current = match[1]
            rows[current] = {}
        elif current:
            match = re.fullmatch(r"\s+(Installed|Candidate):\s+(\S+)\s*", line)
            if match:
                rows[current][match[1].lower()] = match[2]
    return rows


def summarize_log(text: str) -> dict:
    patterns = {"seccomp": r"seccomp", "bpf": r"\bbpf\b|bpf_",
                "allocation": r"allocation fail|out of memory|vmalloc.*fail",
                "apparmor_denied": r"apparmor.*denied"}
    return {"matching_line_counts": {
        key: sum(bool(re.search(pattern, line, re.I)) for line in text.splitlines())
        for key, pattern in patterns.items()},
        "interpretation": "Last 500 current-boot kernel messages only; no match does not rule out failure."}


def collect(evidence: Path | None = None) -> dict:
    release = platform.release()
    report = {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "mode": "DIAGNOSTIC_ONLY", "hostname": platform.node(), "kernel_release": release,
              "architecture": platform.machine(), "euid": os.geteuid(),
              "host_repair": "NOT_PERFORMED", "restore_test": "NOT_RUN",
              "container_exec_probe": "NOT_RUN", "production_deployment_authorized": False,
              "security_settings_changed": False, "evidence": inspect_evidence(evidence),
              "collection_gaps": []}
    if evidence and report["evidence"]["status"] != "READ":
        report["collection_gaps"].append("evidence")
    for name, path in (("boot_id", Path("/proc/sys/kernel/random/boot_id")),
                       ("uptime", Path("/proc/uptime"))):
        item = read_text(path, 128)
        report[name] = {"status": item["status"], "value": item.get("text", "").strip() or None}
        if item["status"] != "READ":
            report["collection_gaps"].append(name)
    files = {
        "os": (Path("/usr/lib/os-release") if Path("/etc/os-release").is_symlink() else Path("/etc/os-release"), {"ID", "VERSION_ID", "VERSION_CODENAME"}, "="),
        "kernel_config": (Path("/boot") / f"config-{release}", CONFIG_KEYS, "="),
        "memory": (Path("/proc/meminfo"), {"MemTotal", "MemAvailable", "VmallocTotal",
                                               "VmallocUsed", "VmallocChunk", "Slab", "SUnreclaim"}, ":"),
    }
    for name, (path, keys, separator) in files.items():
        item = read_text(path)
        report[name] = {"status": item["status"], "fields": parse_fields(item.get("text", ""), keys, separator)}
        if item["status"] != "READ":
            report["collection_gaps"].append(name)
    report["sysctls"] = {}
    for key in ("bpf_jit_limit", "bpf_jit_enable", "bpf_jit_harden"):
        item = read_text(Path("/proc/sys/net/core") / key, 128)
        raw = item.get("text", "").strip()
        valid = item["status"] == "READ" and raw.isdigit()
        report["sysctls"][key] = {"status": "READ" if valid else "UNAVAILABLE",
                                    "value": int(raw) if valid else None}
        if not valid:
            report["collection_gaps"].append(key)
    item = read_text(Path("/proc/vmallocinfo"), 8 * LIMIT)
    report["vmalloc"] = {"status": item["status"], **summarize_vmalloc(item.get("text", ""))}
    if item["status"] != "READ":
        report["collection_gaps"].append("vmalloc")
    report["processes"] = summarize_processes()
    if report["processes"]["status"] != "READ":
        report["collection_gaps"].append("processes")
    for name, parser in (("packages", summarize_packages), ("candidates", summarize_candidates),
                         ("kernel_log", summarize_log)):
        item = run_readonly(name)
        report[name] = {"status": item["status"], "returncode": item.get("returncode"),
                        "summary": parser(item.get("stdout", ""))}
        gap = command_collection_gap(name, item, report[name]["summary"])
        if gap:
            report[name]["collection_gap_reason"] = gap
            report["collection_gaps"].append(name)
        elif name == "packages" and item.get("returncode") == 1:
            report[name]["collection_note"] = "expected_packages_absent"
    report["candidate_note"] = "Local APT cache only; not refreshed, not selected upgrade targets."
    report["diagnosis"] = classify_error("") if report["evidence"]["status"] != "READ" else {
        key: report["evidence"][key] for key in ("classification", "bpf_jit_exhaustion",
                                                "kernel_runtime_incompatibility")}
    report["collection_status"] = "PARTIAL" if report["collection_gaps"] else "COMPLETE"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, help="Existing protected restore-test JSON; read only")
    parser.add_argument("--expected-hostname", help="Abort before collection unless this hostname matches")
    args = parser.parse_args(argv)
    if args.expected_hostname and args.expected_hostname != platform.node():
        print(json.dumps({"error": "HOSTNAME_MISMATCH", "host_repair": "NOT_PERFORMED",
                          "production_deployment_authorized": False}))
        return 2
    report = collect(args.evidence)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if args.evidence and report["evidence"]["status"] != "READ" else 0


if __name__ == "__main__":
    raise SystemExit(main())
