#!/usr/bin/env python3
"""Redacting repository secret scan: never emits matched values."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True
).strip())
MAX_TEXT = 10 * 1024 * 1024
SKIP_PARTS = {".git", "__pycache__", "node_modules"}
PLACEHOLDERS = re.compile(
    r"(?i)^(?:false|true|none|null|changeme|replace[_-]?me|example|placeholder|"
    r"redacted|not[_-]?set|disabled|\$\{[^}]+\}|<[^>]+>|/[^ ]+)$"
)
PATTERNS = [
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]
ASSIGNMENT = re.compile(
    rb"""(?ix)
    \b(password|passwd|secret|token|api[_-]?key|encryption[_-]?key|
       redis[_-]?password|smtp[_-]?password|sip[_-]?password|
       client[_-]?secret|private[_-]?key)
    \s*[:=]\s*["']?([^\s,"'#;]{8,})
    """
)
SENSITIVE_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".sql", ".dump", ".backup",
    ".pgcustom", ".tar", ".tgz", ".zip", ".gz",
}


def fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:16]


def ignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path.relative_to(ROOT))],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    findings: list[tuple[str, str, str, str]] = []
    artifacts: list[tuple[str, int, str, str]] = []
    scanned = 0
    for directory, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
        for name in names:
            path = Path(directory) / name
            try:
                info = path.lstat()
            except OSError:
                continue
            if not path.is_file():
                continue
            rel = str(path.relative_to(ROOT))
            is_ignored = ignored(path)
            suffixes = {s.lower() for s in path.suffixes}
            if suffixes & SENSITIVE_SUFFIXES or info.st_size >= 1024 * 1024:
                artifacts.append((
                    rel, info.st_size,
                    "ignored" if is_ignored else "not-ignored",
                    "sensitive-extension" if suffixes & SENSITIVE_SUFFIXES else "large-file",
                ))
            if info.st_size > MAX_TEXT:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:8192]:
                continue
            scanned += 1
            for category, pattern in PATTERNS:
                for match in pattern.finditer(data):
                    findings.append((
                        rel, category, fingerprint(match.group(0)),
                        "ignored" if is_ignored else "not-ignored",
                    ))
            for match in ASSIGNMENT.finditer(data):
                value = match.group(2).rstrip(b")]}")
                decoded = value.decode("utf-8", "ignore")
                if PLACEHOLDERS.match(decoded) or decoded.startswith(("$", "{{")):
                    continue
                findings.append((
                    rel,
                    "credential-assignment:" + match.group(1).decode().lower(),
                    fingerprint(value),
                    "ignored" if is_ignored else "not-ignored",
                ))

    out = ROOT / "reports/github/SECRET_SCAN_FINDINGS.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        handle.write("path,category,redacted_sha256_prefix,git_policy\n")
        for row in sorted(set(findings)):
            handle.write(",".join('"' + value.replace('"', '""') + '"' for value in row) + "\n")

    artifact_out = ROOT / "reports/github/SENSITIVE_ARTIFACT_INVENTORY.csv"
    with artifact_out.open("w", encoding="utf-8") as handle:
        handle.write("path,bytes,git_policy,classification\n")
        for path, size, policy, category in sorted(set(artifacts)):
            handle.write(f'"{path}",{size},"{policy}","{category}"\n')

    print(f"TEXT_FILES_SCANNED={scanned}")
    print(f"REDACTED_FINDINGS={len(set(findings))}")
    print(f"SENSITIVE_OR_LARGE_ARTIFACTS={len(set(artifacts))}")
    return 1 if any(row[3] == "not-ignored" for row in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
