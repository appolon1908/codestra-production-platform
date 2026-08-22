#!/usr/bin/env python3
"""Verify restored filestore objects through Odoo's attachment API."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class FilestoreReadError(RuntimeError):
    """Raised when Odoo cannot return the expected restored object bytes."""


def verify(env: Any) -> dict[str, int]:
    attachments = env["ir.attachment"].sudo().search(
        [("store_fname", "!=", False)], order="id"
    )
    checked = 0
    for attachment in attachments:
        try:
            payload = attachment.raw
        except Exception as exc:
            raise FilestoreReadError(
                f"Odoo failed to read filestore attachment id={attachment.id}"
            ) from exc
        if payload is None:
            raise FilestoreReadError(
                f"Odoo returned no bytes for filestore attachment id={attachment.id}"
            )
        checksum = hashlib.sha1(payload).hexdigest()
        if checksum != attachment.checksum:
            raise FilestoreReadError(
                f"Odoo returned a checksum mismatch for attachment id={attachment.id}"
            )
        checked += 1
        attachment.invalidate_recordset(["raw"])

    if checked == 0:
        raise FilestoreReadError("restored database has no filestore-backed attachments")
    return {"odoo_filestore_objects_read": checked, "read_failures": 0}


def run(env: Any) -> None:
    print("ODOO_FILESTORE_READ_RESULT=" + json.dumps(verify(env), sort_keys=True))

