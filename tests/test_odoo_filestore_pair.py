import hashlib
import os
from pathlib import Path

import pytest

from operations.restore.validate_odoo_filestore_pair import ValidationError, validate


def fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    metadata = tmp_path / "BACKUP-METADATA"
    metadata.write_text(
        "BACKUP_ID=pair-1\nDATABASE=codestra_odoo\n"
        "FILESTORE_RELATIVE=filestore/codestra_odoo_restore\n"
        f"ODOO_UID={os.getuid()}\nODOO_GID={os.getgid()}\n"
    )
    data = tmp_path / "data"
    item = data / "filestore/codestra_odoo_restore/aa/object"
    item.parent.mkdir(parents=True)
    item.write_bytes(b"controlled-fixture")
    attachments = tmp_path / "attachments.tsv"
    attachments.write_text(f"aa/object|{hashlib.sha1(item.read_bytes()).hexdigest()}\n")
    return metadata, data, attachments


def test_valid_pair(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    assert validate(metadata, data, attachments, "pair-1")["missing_objects"] == 0


def test_rejects_wrong_backup_id(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    with pytest.raises(ValidationError, match="backup ID mismatch"):
        validate(metadata, data, attachments, "pair-2")


def test_rejects_missing_object(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    next((data / "filestore").rglob("object")).unlink()
    with pytest.raises(ValidationError, match="missing filestore"):
        validate(metadata, data, attachments, "pair-1")


def test_rejects_checksum_mismatch(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    next((data / "filestore").rglob("object")).write_bytes(b"modified")
    with pytest.raises(ValidationError, match="checksum mismatches"):
        validate(metadata, data, attachments, "pair-1")


def test_rejects_blank_checksum(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    attachments.write_text("aa/object|\n")
    with pytest.raises(ValidationError, match="blank filename or checksum"):
        validate(metadata, data, attachments, "pair-1")


def test_preserves_orphan_names(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    orphan = data / "filestore/codestra_odoo_restore/bb/orphan"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    result = validate(metadata, data, attachments, "pair-1")
    assert result["orphan_files"] == ["bb/orphan"]


def test_rejects_conflicting_duplicate_checksum(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    original = attachments.read_text().strip()
    attachments.write_text(f"{original}\naa/object|{'0' * 40}\n")
    with pytest.raises(ValidationError, match="conflicting checksums"):
        validate(metadata, data, attachments, "pair-1")


def test_rejects_nontraversable_filestore_directory(tmp_path: Path) -> None:
    metadata, data, attachments = fixture(tmp_path)
    shard = data / "filestore/codestra_odoo_restore/aa"
    shard.chmod(0o600)
    with pytest.raises(ValidationError, match="directory traversal failures"):
        validate(metadata, data, attachments, "pair-1")
