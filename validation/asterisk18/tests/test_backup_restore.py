import hashlib
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

from harness import EVIDENCE, ROOT, RUNTIME, login, record, sha256


def test_restricted_backup_exact_restore_and_health():
    files = [RUNTIME / "manager.conf", RUNTIME / "pki/valid.pem",
             RUNTIME / "pki/valid.chain.pem", RUNTIME / "pki/valid.key"]
    before = {str(path.relative_to(RUNTIME)): (sha256(path), stat.S_IMODE(path.stat().st_mode)) for path in files}
    backup = RUNTIME / "backup"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(mode=0o700)
    started = time.monotonic()
    for path in files:
        destination = backup / path.relative_to(RUNTIME)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    manifest = backup / "SHA256SUMS"
    manifest.write_text("".join(f"{digest}  {name}\n" for name, (digest, _) in before.items()), encoding="utf-8")
    os.chmod(manifest, 0o600)

    # Apply a synthetic certificate/config mutation and prove it exists.
    (RUNTIME / "manager.conf").write_text("[general]\nenabled=no\n", encoding="utf-8")
    assert sha256(RUNTIME / "manager.conf") != before["manager.conf"][0]

    # Exact restore operation: install each allowlisted backup path with its recorded mode.
    for name, (_, mode) in before.items():
        shutil.copy2(backup / name, RUNTIME / name)
        os.chmod(RUNTIME / name, mode)
    restored = {name: (sha256(RUNTIME / name), stat.S_IMODE((RUNTIME / name).stat().st_mode)) for name in before}
    assert restored == before

    # Restart disposable TLS proxy/container, then validate Asterisk, TLS hostname, and AMI auth.
    subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yaml"), "restart", "asterisk"], check=True)
    subprocess.run([str(ROOT / "scripts/wait-for-health.sh")], check=True)
    assert login().get("Response") == "Success"
    elapsed = time.monotonic() - started
    assert elapsed < 600
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / "rollback-seconds.txt").write_text(f"{elapsed:.3f}\n", encoding="utf-8")
    record("backup_restore", result="PASS", rollback_seconds=round(elapsed, 3))
