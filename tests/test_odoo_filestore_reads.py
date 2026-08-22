from __future__ import annotations

import hashlib

import pytest

from operations.restore.verify_odoo_filestore_reads import FilestoreReadError, verify


class Attachment:
    def __init__(self, attachment_id: int, payload: bytes, checksum: str | None = None):
        self.id = attachment_id
        self.raw = payload
        self.checksum = checksum or hashlib.sha1(payload).hexdigest()
        self.invalidated = []

    def invalidate_recordset(self, fields):
        self.invalidated.append(fields)


class AttachmentModel:
    def __init__(self, records):
        self.records = records
        self.domain = None

    def sudo(self):
        return self

    def search(self, domain, order):
        self.domain = domain
        assert order == "id"
        return self.records


class Environment(dict):
    pass


def test_reads_every_filestore_object_through_odoo_api() -> None:
    records = [Attachment(1, b"first"), Attachment(2, b"second")]
    model = AttachmentModel(records)
    result = verify(Environment({"ir.attachment": model}))
    assert result == {"odoo_filestore_objects_read": 2, "read_failures": 0}
    assert model.domain == [("store_fname", "!=", False)]
    assert all(record.invalidated == [["raw"]] for record in records)


def test_fails_when_odoo_returns_different_bytes() -> None:
    record = Attachment(7, b"restored", checksum=hashlib.sha1(b"expected").hexdigest())
    with pytest.raises(FilestoreReadError, match="checksum mismatch"):
        verify(Environment({"ir.attachment": AttachmentModel([record])}))


def test_fails_when_no_filestore_objects_exist() -> None:
    with pytest.raises(FilestoreReadError, match="no filestore-backed attachments"):
        verify(Environment({"ir.attachment": AttachmentModel([])}))
