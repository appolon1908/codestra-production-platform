from __future__ import annotations

import os
import stat
import urllib.parse

from odoo import _, api, models
from odoo.exceptions import ValidationError


MAX_SECRET_FILE_BYTES = 4096


class CodestraCrmCallFollowupAutomationHardening(models.Model):
    """Harden secret and destination handling for the outbox worker."""

    _inherit = "codestra.crm.call.followup.outbox"

    @api.model
    def _read_secret_file(self, parameter_key, minimum_length=16):
        path_value = str(
            self._parameter(parameter_key, "") or ""
        ).strip()
        if not path_value:
            raise ValidationError(
                _("A required automation secret file is not configured.")
            )

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = -1
        try:
            descriptor = os.open(path_value, flags)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValidationError(
                    _("A required automation secret file is not regular.")
                )
            if metadata.st_mode & 0o022:
                raise ValidationError(
                    _(
                        "A required automation secret file must not be "
                        "group- or world-writable."
                    )
                )
            if metadata.st_size > MAX_SECRET_FILE_BYTES:
                raise ValidationError(
                    _("A required automation secret file is too large.")
                )

            chunks = []
            total = 0
            while total <= MAX_SECRET_FILE_BYTES:
                chunk = os.read(
                    descriptor,
                    min(1024, MAX_SECRET_FILE_BYTES + 1 - total),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > MAX_SECRET_FILE_BYTES:
                raise ValidationError(
                    _("A required automation secret file is too large.")
                )
            raw_secret = b"".join(chunks)
        except ValidationError:
            raise
        except OSError as exc:
            raise ValidationError(
                _(
                    "A required automation secret file cannot be opened "
                    "safely."
                )
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        try:
            secret = raw_secret.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ValidationError(
                _("A required automation secret is not valid UTF-8.")
            ) from exc
        if not minimum_length <= len(secret) <= MAX_SECRET_FILE_BYTES:
            raise ValidationError(
                _("A required automation secret has an invalid length.")
            )
        return secret

    @api.model
    def _delivery_config(self):
        target_url = str(
            self._parameter(
                "codestra.call_followup_automation.target_url",
                "",
            )
            or ""
        ).strip()
        parsed = urllib.parse.urlparse(target_url)
        if parsed.params or parsed.query:
            raise ValidationError(
                _(
                    "The automation target URL cannot contain path "
                    "parameters or a query string."
                )
            )
        return super()._delivery_config()
