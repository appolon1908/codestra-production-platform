"""Run the real bootstrap transaction fragments against temporary files only.

No root-only installer, host path, audit service or real immutable flag is used.
The transaction source is extracted unchanged; chattr/lsattr are filesystem
simulations, and controlled copy failures exercise the EXIT handler.
"""

from pathlib import Path
import shlex
import subprocess

import pytest


BOOTSTRAP = (
    Path(__file__).resolve().parents[1]
    / "operations/host-auditd/bootstrap-provider-host-auditd-launcher"
)


@pytest.fixture
def sandbox(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    flags = tmp_path / "flags"
    flags.mkdir()
    targets = [tmp_path / f"target-{i}" for i in range(5)]
    for i, target in enumerate(targets):
        target.write_text(f"original-{i}")
        target.chmod(0o600 + i)
        if i % 2 == 0:
            (flags / target.name).touch()
    return tmp_path, work, flags, targets


def run_fragment(sandbox, body, *, snapshot=False, fail_copy=""):
    root, work, flags, targets = sandbox
    text = BOOTSTRAP.read_text()
    transaction = text[text.index("cleanup() {"):text.index("trap rollback_bootstrap EXIT")]
    snapshot_loop = text[
        text.index('for index in "${!targets[@]}"; do', text.index("trap rollback_bootstrap EXIT"))
        :text.index("/usr/bin/install -d")
    ]
    # Only these external commands are substituted. All real cp/rm/cmp/find/sync
    # operands are generated below from this test's temporary directory.
    transaction = transaction.replace("/usr/bin/chattr", "fake_chattr").replace("/usr/bin/lsattr", "fake_lsattr").replace("/usr/bin/cp", "copy_file")
    snapshot_loop = snapshot_loop.replace("/usr/bin/lsattr", "fake_lsattr").replace("/usr/bin/cp", "copy_file")
    variables = {
        "work": work, "flags": flags, "oplog": root / "operations.log",
        "installer_target": targets[0], "launcher_target": targets[1],
        "python_target": targets[2], "digest_target": targets[3],
        "runtime_path_target": targets[4], "fail_copy": fail_copy,
    }
    assignments = "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in variables.items())
    mocks = r'''
fake_chattr() {
  local name=${2##*/}
  printf 'chattr %s %s\n' "$1" "$name" >> "$oplog"
  if [ "$1" = +i ]; then
    touch "$flags/$name"
  else
    rm -f "$flags/$name"
  fi
}
fake_lsattr() {
  local name=${2##*/} attributes=----------------------
  [ ! -f "$flags/$name" ] || attributes=----i-----------------
  printf '%s %s\n' "$attributes" "$2"
}
copy_file() {
  local destination=${!#}
  if [ -n "$fail_copy" ] && [ "${destination##*/}" = "$fail_copy" ]; then
    # Simulate a partial checkpoint or restoration without reporting success.
    printf 'partial' > "$destination"
    return 31
  fi
  command /usr/bin/cp "$@"
}
'''
    script = root / "transaction.sh"
    script.write_text("set -euo pipefail\n" + assignments + "\n" + mocks + transaction + "trap rollback_bootstrap EXIT\n" + (snapshot_loop if snapshot else "") + "\n" + body + "\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=10, check=False)


def assert_originals(sandbox):
    _, _, flags, targets = sandbox
    for i, target in enumerate(targets):
        assert target.read_text() == f"original-{i}"
        assert target.stat().st_mode & 0o777 == 0o600 + i
        assert (flags / target.name).exists() == (i % 2 == 0)


def test_prerequisite_failure_never_removes_uncheckpointed_targets(sandbox):
    result = run_fragment(sandbox, "exit 17")
    assert result.returncode == 17
    assert_originals(sandbox)
    assert not sandbox[1].exists()
    assert not (sandbox[0] / "operations.log").exists()


@pytest.mark.parametrize("failed_index", range(5))
def test_partial_snapshot_failure_does_not_unseal_or_mutate_targets(sandbox, failed_index):
    result = run_fragment(sandbox, "exit 0", snapshot=True, fail_copy=f"backup-{failed_index}")
    assert result.returncode == 31
    assert_originals(sandbox)
    assert not (sandbox[0] / "operations.log").exists()


def test_dangling_target_symlink_fails_without_touching_other_targets(sandbox):
    target = sandbox[3][-1]
    target.unlink()
    target.symlink_to(sandbox[0] / "nonexistent")
    result = run_fragment(sandbox, "exit 0", snapshot=True)
    assert result.returncode != 0
    assert target.is_symlink()
    for i, path in enumerate(sandbox[3][:-1]):
        assert path.read_text() == f"original-{i}"
    assert not (sandbox[0] / "operations.log").exists()


def test_failed_install_restores_bytes_modes_and_prior_immutable_state(sandbox):
    result = run_fragment(sandbox, '''
touched=(0 1 2 3 4)
for target in "${targets[@]}"; do
  printf new > "$target"
  chmod 0755 "$target"
  fake_chattr +i "$target"
done
exit 23
''', snapshot=True)
    assert result.returncode == 23
    assert_originals(sandbox)
    assert not sandbox[1].exists()


def test_only_checkpointed_originally_absent_targets_are_removed(sandbox):
    sandbox[3][1].unlink()
    sandbox[3][3].unlink()
    result = run_fragment(sandbox, '''
touched=(1 3)
printf new > "${targets[1]}"
printf new > "${targets[3]}"
exit 19
''', snapshot=True)
    assert result.returncode == 19
    assert not sandbox[3][1].exists()
    assert not sandbox[3][3].exists()
    for i in (0, 2, 4):
        assert sandbox[3][i].read_text() == f"original-{i}"


def test_missing_checkpoint_is_not_treated_as_original_absence(sandbox):
    result = run_fragment(sandbox, "touched=(0)\nexit 19")
    assert result.returncode != 0
    assert sandbox[3][0].read_text() == "original-0"
    assert sandbox[1].is_dir()
    assert "ROLLBACK=FAIL" in result.stderr


def test_missing_target_is_restored_from_captured_local_snapshot(sandbox):
    result = run_fragment(sandbox, 'touched=(0)\nrm "${targets[0]}"\nexit 29', snapshot=True)
    assert result.returncode == 29
    assert_originals(sandbox)


def test_failed_restore_keeps_checkpoints_and_continues_other_restorations(sandbox):
    result = run_fragment(sandbox, '''
touched=(0 1)
printf new > "${targets[0]}"
printf new > "${targets[1]}"
exit 21
''', snapshot=True, fail_copy="target-0")
    assert result.returncode != 0
    assert "ROLLBACK=FAIL" in result.stderr
    assert sandbox[1].is_dir()
    assert (sandbox[1] / "backup-0").read_text() == "original-0"
    assert sandbox[3][1].read_text() == "original-1"


def test_displaced_symlink_is_never_followed_during_restore(sandbox):
    outside = sandbox[0] / "outside"
    outside.write_text("do-not-touch")
    result = run_fragment(sandbox, f'''touched=(0)
rm "${{targets[0]}}"
ln -s {shlex.quote(str(outside))} "${{targets[0]}}"
exit 27
''', snapshot=True)
    assert result.returncode != 0
    assert outside.read_text() == "do-not-touch"
    assert sandbox[1].is_dir()
    assert "ROLLBACK=FAIL" in result.stderr


def test_successful_commit_does_not_run_rollback(sandbox):
    result = run_fragment(sandbox, '''
touched=(0)
printf accepted > "${targets[0]}"
committed=true
exit 0
''', snapshot=True)
    assert result.returncode == 0
    assert sandbox[3][0].read_text() == "accepted"
    assert not sandbox[1].exists()
    assert not (sandbox[0] / "operations.log").exists()


def test_shell_syntax_and_snapshot_before_unlock_contract():
    result = subprocess.run(["bash", "-n", str(BOOTSTRAP)], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    text = BOOTSTRAP.read_text().split("trap rollback_bootstrap EXIT", 1)[1]
    assert text.index('"$work/backup-$index"') < text.index('touched+=("$index")')
    assert text.index('touched+=("$index")') < text.index('/usr/bin/chattr -i "$target"')
