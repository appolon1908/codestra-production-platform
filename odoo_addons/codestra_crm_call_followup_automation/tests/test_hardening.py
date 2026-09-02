import os
from pathlib import Path
import tempfile

from odoo.exceptions import ValidationError

from .test_outbox import TestCodestraCrmCallFollowupOutbox


class TestCodestraCrmCallFollowupAutomationHardening(
    TestCodestraCrmCallFollowupOutbox
):
    def test_secret_reader_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("x" * 32, encoding="utf-8")
            target.chmod(0o600)
            link = root / "secret"
            os.symlink(target, link)
            self.env["ir.config_parameter"].sudo().set_param(
                "codestra.test.secret_file",
                str(link),
            )

            with self.assertRaisesRegex(
                ValidationError,
                "cannot be opened safely",
            ):
                self.outbox._read_secret_file(
                    "codestra.test.secret_file",
                    minimum_length=16,
                )

    def test_secret_reader_rejects_writable_secret_files(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "secret"
            secret.write_text("x" * 32, encoding="utf-8")
            secret.chmod(0o622)
            self.env["ir.config_parameter"].sudo().set_param(
                "codestra.test.secret_file",
                str(secret),
            )

            with self.assertRaisesRegex(
                ValidationError,
                "group- or world-writable",
            ):
                self.outbox._read_secret_file(
                    "codestra.test.secret_file",
                    minimum_length=16,
                )

    def test_target_url_rejects_query_credentials_before_secret_read(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param(
            "codestra.call_followup_automation.target_url",
            "https://middleware.example.test/events?token=forbidden",
        )
        parameters.set_param(
            "codestra.call_followup_automation.tenant_id",
            "test-tenant",
        )
        parameters.set_param(
            "codestra.call_followup_automation.allowed_hosts",
            "middleware.example.test",
        )

        with self.assertRaisesRegex(
            ValidationError,
            "query string",
        ):
            self.outbox._delivery_config()
