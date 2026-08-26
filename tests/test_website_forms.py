import os
import tempfile
import unittest
from unittest.mock import patch

from control_plane_service.core import ControlPlaneError, Store
from control_plane_service.forms import FormService, REGISTRY


class Headers(dict):
    pass


class WebsiteFormTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp()
        os.close(handle)
        self.store = Store(self.path)
        self.store.crm_register_customer(
            "forms", "forms-consumer", "forms-site", True,
            "Codestra", "Website Forms Intake",
        )
        self.previous = os.environ.get("FORM_CRM_CUSTOMER_ID")
        os.environ["FORM_CRM_CUSTOMER_ID"] = "forms"
        self.service = FormService(self.store)
        self.headers = Headers({
            "Origin": "https://codestra.co",
            "Idempotency-Key": "synthetic-form-key",
            "X-Correlation-ID": "synthetic-form-correlation",
        })

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("FORM_CRM_CUSTOMER_ID", None)
        else:
            os.environ["FORM_CRM_CUSTOMER_ID"] = self.previous
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except FileNotFoundError:
                pass

    @staticmethod
    def sales_payload():
        return {
            "full_name": "Synthetic Website User",
            "email": "synthetic@example.invalid",
            "company_size": "1-10",
            "message": "Synthetic contract test",
            "honeypot": "",
        }

    def test_registry_contains_only_versioned_bounded_contracts(self):
        self.assertEqual(REGISTRY["sales-contact"]["classification"], "contact")
        self.assertEqual(REGISTRY["electronic-billing-registration"]["classification"], "registration")
        self.assertTrue(all(spec["version"] == "1.0" for spec in REGISTRY.values()))
        self.assertTrue(all(spec["odoo_target"] == "crm.lead" for spec in REGISTRY.values()))
        self.assertTrue(all(spec["n8n_event"] == "crm.lead.created" for spec in REGISTRY.values()))

    def test_origin_unknown_field_bot_and_typed_schema_are_denied(self):
        payload = self.sales_payload()
        with self.assertRaisesRegex(ControlPlaneError, "origin_denied"):
            self.service.submit("sales-contact", payload, Headers({**self.headers, "Origin": "https://evil.invalid"}), 100)
        with self.assertRaisesRegex(ControlPlaneError, "unsupported_fields:company_id"):
            self.service.submit("sales-contact", {**payload, "company_id": 3}, self.headers, 100)
        with self.assertRaisesRegex(ControlPlaneError, "bot_rejected"):
            self.service.submit("sales-contact", {**payload, "honeypot": "robot"}, self.headers, 100)
        with self.assertRaisesRegex(ControlPlaneError, "invalid_field:message"):
            self.service.submit("sales-contact", {**payload, "message": {"unexpected": True}}, self.headers, 100)

    def test_body_limit_and_consent_are_enforced(self):
        with self.assertRaisesRegex(ControlPlaneError, "body_too_large"):
            self.service.submit("sales-contact", self.sales_payload(), self.headers, 16385)
        demo = {
            "full_name": "Synthetic Website User", "work_email": "synthetic@example.invalid",
            "phone_number": "+1 555 010 9999", "consent": False,
        }
        with self.assertRaisesRegex(ControlPlaneError, "contact_consent_required"):
            self.service.submit("demo-request", demo, self.headers, 100)
        with self.assertRaisesRegex(ControlPlaneError, "invalid_field:sms_consent"):
            self.service.submit("demo-request", {**demo, "consent": True, "sms_consent": "yes"}, self.headers, 100)

    def test_valid_idempotent_duplicate_and_conflict(self):
        created = {"external_id": "form-sales-contact-stable"}
        with patch("control_plane_service.forms.CrmService.call", return_value=(201, created)), \
             patch("control_plane_service.forms.CrmService.emit") as emit:
            status, first = self.service.submit("sales-contact", self.sales_payload(), self.headers, 100)
            self.assertEqual(status, 201)
            self.assertFalse(first["duplicate"])
            replay_status, replay = self.service.submit("sales-contact", self.sales_payload(), self.headers, 100)
            self.assertEqual(replay_status, 201)
            self.assertTrue(replay["duplicate"])
            emit.assert_called_once()
            with self.assertRaisesRegex(ControlPlaneError, "idempotency_conflict"):
                self.service.submit("sales-contact", {**self.sales_payload(), "message": "changed"}, self.headers, 100)

    def test_odoo_and_n8n_failure_boundaries(self):
        with patch("control_plane_service.forms.CrmService.call", side_effect=ControlPlaneError("odoo_unavailable")):
            with self.assertRaisesRegex(ControlPlaneError, "odoo_unavailable"):
                self.service.submit("sales-contact", self.sales_payload(), self.headers, 100)
        with patch("control_plane_service.forms.CrmService.call", return_value=(201, {"external_id": "form-stable"})), \
             patch("control_plane_service.forms.CrmService.emit", side_effect=ControlPlaneError("n8n_unavailable")):
            with self.assertRaisesRegex(ControlPlaneError, "n8n_unavailable"):
                self.service.submit("sales-contact", self.sales_payload(), self.headers, 100)
            self.assertEqual(self.store.crm_object("forms", "form-sales-contact-" + __import__("hashlib").sha256(
                b"sales-contact|synthetic@example.invalid|").hexdigest()[:24] + "-" + __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%d"))["odoo_model"], "crm.lead")


if __name__ == "__main__":
    unittest.main()
