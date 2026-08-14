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
