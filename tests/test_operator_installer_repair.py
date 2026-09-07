from __future__ import annotations

import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "operations" / "production-operator"
STAGER = PACKAGE / "stage-operator-release.py"
INSTALLER = PACKAGE / "install-server-a-operator.sh"


def installer_function(name: str) -> str:
    source = INSTALLER.read_text()
    start = source.index(f"{name}() {{")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def run_shell(source: str, *args: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", source, "installer-regression", *(str(arg) for arg in args)],
        text=True,
        capture_output=True,
        check=False,
    )


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
    restore_lines = [
        line.strip() for line in source.splitlines() if line.strip().startswith("restore_path /")
    ]
    assert restore_lines
    assert all(line.endswith("|| rollback_failed=1") for line in restore_lines)


@pytest.mark.parametrize("failed_command", ["rm", "cp"])
def test_actual_sh_rollback_failure_survives_later_success(
    tmp_path: Path, failed_command: str
) -> None:
    """A later successful restore must not mask an earlier protected-file failure."""
    rollback = tmp_path / "rollback"
    rollback.mkdir()
    installed = tmp_path / "installed.sha256"
    sudoers = tmp_path / "sudoers"
    installed.write_text("replacement\n")
    sudoers.write_text("replacement\n")
    (rollback / "installed-checksum").write_text("original checksum\n")
    (rollback / "sudoers").write_text("original sudoers\n")
    shell = installer_function("restore_path") + r'''
rollback_dir=$1
installed=$2
sudoers=$3
real_rm=$(command -v rm)
real_cp=$(command -v cp)
rm() {
  if [ "$FAILED_COMMAND" = rm ] && [ "$3" = "$installed" ]; then return 1; fi
  "$real_rm" "$@"
}
cp() {
  if [ "$FAILED_COMMAND" = cp ] && [ "$4" = "$installed" ]; then return 1; fi
  "$real_cp" "$@"
}
rollback_sequence() {
  rollback_failed=0
  restore_path "$installed" installed-checksum || rollback_failed=1
  restore_path "$sudoers" sudoers || rollback_failed=1
  return "$rollback_failed"
}
status=PASS
rollback_sequence || status=FAIL
printf 'ROLLBACK_RESULT=%s\n' "$status"
test "$status" = FAIL
test "$(cat "$sudoers")" = 'original sudoers'
'''
    result = subprocess.run(
        ["/bin/sh", "-c", shell, "installer-regression", str(rollback), str(installed), str(sudoers)],
        env={**os.environ, "FAILED_COMMAND": failed_command},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ROLLBACK_RESULT=FAIL" in result.stdout


def test_actual_sh_distinguishes_absent_marker_from_missing_backup(tmp_path: Path) -> None:
    rollback = tmp_path / "rollback"
    rollback.mkdir()
    absent_target = tmp_path / "originally-absent"
    missing_target = tmp_path / "missing-evidence"
    absent_target.write_text("replacement\n")
    missing_target.write_text("replacement\n")
    (rollback / "absent.absent").touch()
    shell = installer_function("restore_path") + r'''
rollback_dir=$1
restore_path "$2" absent || exit 10
test ! -e "$2" || exit 11
restore_path "$3" missing && exit 12
exit 0
'''
    result = run_shell(shell, rollback, absent_target, missing_target)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mutation", ["missing", "malformed", "duplicate"])
def test_manifest_validator_never_promotes_invalid_certification(
    tmp_path: Path, mutation: str
) -> None:
    source = (ROOT / "PRODUCTION-DATABASE-MANIFEST.yaml").read_text()
    certification = "certification_status: FAIL"
    assert source.count(certification) == 1
    if mutation == "missing":
        source = source.replace(f"{certification}\n", "")
    elif mutation == "malformed":
        source = source.replace(certification, "certification_status: UNKNOWN")
    else:
        source = source.replace(certification, f"{certification}\n{certification}")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(source)
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/validate_production_database_manifest.py"), str(manifest)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "PRODUCTION_DATABASE_CERTIFICATION_STATUS=PASS" not in result.stdout


def test_valid_fail_manifest_remains_reported_fail() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/validate_production_database_manifest.py"),
            str(ROOT / "PRODUCTION-DATABASE-MANIFEST.yaml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "PRODUCTION_DATABASE_MANIFEST_STRUCTURE=PASS" in result.stdout
    assert "PRODUCTION_DATABASE_CERTIFICATION_STATUS=FAIL" in result.stdout


def test_installer_reports_structural_and_certification_results_separately() -> None:
    source = INSTALLER.read_text()
    assert "'STRUCTURAL_VALIDATION=PASS'" in source
    assert "'DATABASE_MANIFEST_STRUCTURAL_VALIDATION=PASS'" in source
    assert '"DATABASE_CERTIFICATION_STATUS=$database_certification_status"' in source
    assert "'DATABASE_CERTIFICATION=PASS'" not in source


def test_actual_sh_preserves_install_failure_status_when_rollback_fails() -> None:
    shell = installer_function("on_failure") + r'''
rollback() {
  true
  return 1
}
trap on_failure EXIT HUP INT TERM
exit 23
'''
    result = run_shell(shell)
    assert result.returncode == 23
    assert "INSTALL_RESULT=FAIL" in result.stdout
    assert "ROLLBACK_RESULT=FAIL" in result.stdout


@pytest.mark.parametrize("failure", ["remove", "copy"])
def test_restore_failure_forces_rollback_failure(tmp_path: Path, failure: str) -> None:
    source = INSTALLER.read_text()
    functions = source[source.index("restore_path() {") : source.index("on_failure() {")]
    rollback = tmp_path / "rollback"
    rollback.mkdir()
    (rollback / "operator").write_text("previous operator", encoding="utf-8")
    harness = f"""
rollback_dir=$1
installed_checksum_tmp=
installed=1
state_dir_metadata_touched=0
state_dir_existed=0
created_user=0
FAILURE=$2
rm() {{
  if [ "$FAILURE" = remove ] && [ "$3" = /usr/local/sbin/codestra-production-operator ]; then
    return 1
  fi
  return 0
}}
cp() {{
  if [ "$FAILURE" = copy ] && [ "$3" = "$rollback_dir/operator" ]; then
    return 1
  fi
  return 0
}}
systemctl() {{ return 0; }}
sshd() {{ return 0; }}
chown() {{ return 0; }}
chmod() {{ return 0; }}
userdel() {{ return 0; }}
{functions}
rollback
"""
    result = subprocess.run(
        ["sh", "-c", harness, "rollback-test", str(rollback), failure],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr


def test_database_manifest_reporting_separates_structure_from_certification() -> None:
    installer = INSTALLER.read_text()
    validator = (ROOT / "tools/validate_production_database_manifest.py").read_text()
    assert "'DATABASE_CERTIFICATION=PASS'" not in installer
    assert "DATABASE_MANIFEST_STRUCTURAL_VALIDATION=PASS" in installer
    assert 'DATABASE_CERTIFICATION_STATUS=$database_certification_status' in installer
    assert 'print("PRODUCTION_DATABASE_MANIFEST_STRUCTURE=PASS")' in validator
    assert 'PRODUCTION_DATABASE_CERTIFICATION_STATUS={certification_status}' in validator


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


def test_stage_accepts_directory_member_after_its_child(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    archive = make_archive(
        root,
        [
            ("operator/file", tarfile.REGTYPE, b"ok", ""),
            ("operator", tarfile.DIRTYPE, b"", ""),
        ],
    )
    result = run_stage(root, archive, approved(archive))
    assert result.returncode == 0, result.stderr
    assert (root / "staged/release-1/operator/file").read_bytes() == b"ok"


def test_runbook_uses_exact_database_certification_field() -> None:
    runbook = (PACKAGE / "README.md").read_text()
    assert "`DATABASE_CERTIFICATION_STATUS` is read" in runbook
    assert "`DATABASE_CERTIFICATION` is read" not in runbook


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
