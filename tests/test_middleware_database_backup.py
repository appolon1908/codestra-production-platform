from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "operations/recovery/scraper-middleware-offserver.sh"


def test_offhost_backup_is_encrypted_atomic_and_checksummed() -> None:
    source = SCRIPT.read_text()
    assert "umask 077" in source
    assert "codestra_middleware.dump.gpg" in source
    assert "METADATA.env" in source
    assert "sha256sum -c SHA256SUMS" in source
    assert "remote_upload=${remote_root}/.${stamp}.upload" in source
    assert "mv '${remote_upload}' '${remote_dir}'" in source
    assert "codestra_middleware.dump\"" not in source.split("scp -q", 1)[1]


def test_backup_does_not_broaden_remote_privilege_or_prune_remote_state() -> None:
    source = SCRIPT.read_text()
    assert "sudo" not in source
    assert "ssh -o BatchMode=yes" in source
    assert "find \"${remote_root}\"" not in source
    assert "rm -" not in source


def test_backup_records_schema_and_database_size_without_secrets() -> None:
    source = SCRIPT.read_text()
    assert "DATABASE_HEAD=${database_head}" in source
    assert "database_head_before=" in source
    assert "database_head_after=" in source
    assert '"${database_head_before}" != "${database_head_after}"' in source
    assert "DATABASE_SIZE_BYTES=${database_size}" in source
    assert "password" not in source.lower()
    assert "PRIVATE KEY" not in source


def test_retention_counts_only_validated_successful_snapshots() -> None:
    source = SCRIPT.read_text()
    assert "-exec test -s '{}/STATUS.txt'" in source
    assert "success=yes" in source
    assert '"${success}" != yes' in source
