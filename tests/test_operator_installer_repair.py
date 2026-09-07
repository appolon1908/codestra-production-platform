from __future__ import annotations

import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "operations" / "production-operator"
STAGER = PACKAGE / "stage-operator-release.py"
INSTALLER = PACKAGE / "install-server-a-operator.sh"


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "codestra-operator-releases"
    (root / "source").mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (root / "source").chmod(0o700)
    return root


def make_archive(root: Path, members: list[tuple[str, bytes, bytes, str]]) -> Path:
    archive = root / "source" / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name, kind, content, link in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.linkname = link
            if kind == tarfile.REGTYPE:
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
            else:
                bundle.addfile(member)
    archive.chmod(0o600)
    return archive


def run_stage(root: Path, archive: Path, digest: str, release: str = "release-1") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CODESTRA_STAGE_ROOT": str(root)}
    return subprocess.run(
        [str(STAGER), str(archive), digest, release, "--test-root"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def approved(archive: Path) -> str:
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def test_installed_checksum_is_atomic_backed_up_and_rolled_back() -> None:
    source = INSTALLER.read_text()
    target = "/etc/codestra/production-operator/installed.sha256"
    assert f"reject_target_symlink {target}" in source
    assert f"validate_existing_root_target {target} 600" in source
    assert '[ "$(stat -c %h "$target")" -eq 1 ] || fail' in source
    assert f"backup_path {target} installed-checksum" in source
    assert f"restore_path {target} installed-checksum" in source
    assert "installed_checksum_tmp=$(mktemp" in source
    assert 'chmod 0600 "$installed_checksum_tmp"' in source
    assert f'mv -f "$installed_checksum_tmp" {target}' in source
    assert source.index(f"backup_path {target}") < source.index("installed=1")
    assert source.index(f'mv -f "$installed_checksum_tmp" {target}') < source.rindex(
        "/usr/local/libexec/validate-production-database-manifest"
    )
    assert "ROLLBACK_RESULT=$rollback_status" in source
    assert "SOURCE_LOCK_STATUS=NOT_EVALUATED_BY_INSTALLER" in source


def test_installer_manifest_contract_covers_existing_absent_and_failure_boundaries(tmp_path: Path) -> None:
    """Exercise the backup/publish/rollback contract entirely below tmp_path."""
    target = tmp_path / "installed.sha256"
    backup = tmp_path / "backup"
    replacement = b"new manifest\n"
    for original in (None, b"old manifest\n"):
        target.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        if original is not None:
            target.write_bytes(original)
            target.chmod(0o640)
            backup.write_bytes(target.read_bytes())
            backup.chmod(target.stat().st_mode & 0o777)
        # Failure before publication changes nothing.
        assert (target.read_bytes() if target.exists() else None) == original
        # Private atomic publication, followed by a simulated later failure.
        temporary = tmp_path / ".installed.private"
        temporary.write_bytes(replacement)
        temporary.chmod(0o600)
        temporary.replace(target)
        assert target.read_bytes() == replacement
        if backup.exists():
            target.unlink()
            backup.replace(target)
        else:
            target.unlink()
        assert (target.read_bytes() if target.exists() else None) == original
        if original is not None:
            assert target.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("digest,release", [("", "release-1"), ("x" * 64, "release-1"), ("0" * 64, ""), ("0" * 64, "../bad")])
def test_stage_rejects_empty_or_malformed_inputs(tmp_path: Path, digest: str, release: str) -> None:
    root = make_root(tmp_path)
    archive = make_archive(root, [("operator/file", tarfile.REGTYPE, b"ok", "")])
    assert run_stage(root, archive, digest, release).returncode == 2


def test_stage_valid_archive_with_safe_tree(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    archive = make_archive(root, [("operator/file", tarfile.REGTYPE, b"ok", "")])
    result = run_stage(root, archive, approved(archive))
    assert result.returncode == 0, result.stderr
    target = root / "staged" / "release-1" / "operator" / "file"
    assert target.read_bytes() == b"ok"
    assert target.stat().st_mode & 0o777 == 0o644
    assert target.stat().st_uid == os.geteuid()
    assert "PRODUCTION_INSTALLED=NO" in result.stdout
    assert not list((root / "snapshots").iterdir())


def test_stage_rejects_wrong_digest_and_existing_destination(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    archive = make_archive(root, [("file", tarfile.REGTYPE, b"ok", "")])
    assert run_stage(root, archive, "0" * 64).returncode == 2
    (root / "staged" / "release-1").mkdir(parents=True)
    assert run_stage(root, archive, approved(archive)).returncode == 2


@pytest.mark.parametrize(
    "members",
    [
        [("../escape", tarfile.REGTYPE, b"x", "")],
        [("/absolute", tarfile.REGTYPE, b"x", "")],
        [("link", tarfile.SYMTYPE, b"", "target")],
        [("hard", tarfile.LNKTYPE, b"", "target")],
        [("fifo", tarfile.FIFOTYPE, b"", "")],
        [("same", tarfile.REGTYPE, b"a", ""), ("same", tarfile.REGTYPE, b"b", "")],
        [("parent", tarfile.REGTYPE, b"a", ""), ("parent/child", tarfile.REGTYPE, b"b", "")],
    ],
)
def test_stage_rejects_unsafe_archive_members(tmp_path: Path, members) -> None:
    root = make_root(tmp_path)
    archive = make_archive(root, members)
    assert run_stage(root, archive, approved(archive)).returncode == 2
    assert not (tmp_path / "escape").exists()


def test_stage_rejects_unsafe_source_and_destination_paths(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    outside = tmp_path / "outside.tar"
    outside.write_bytes(b"not an archive")
    outside.chmod(0o600)
    assert run_stage(root, outside, hashlib.sha256(outside.read_bytes()).hexdigest()).returncode == 2
    archive = make_archive(root, [("file", tarfile.REGTYPE, b"ok", "")])
    archive.chmod(0o666)
    assert run_stage(root, archive, approved(archive)).returncode == 2
    archive.chmod(0o600)
    (root / "staged").symlink_to(tmp_path / "elsewhere")
    assert run_stage(root, archive, approved(archive)).returncode == 2
