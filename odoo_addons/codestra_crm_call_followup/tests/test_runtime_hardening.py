from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraCrmCallFollowupRuntimeHardening(TransactionCase):
    def test_html_notes_are_not_registered_for_field_tracking(self):
        field = self.env["codestra.crm.call.followup"]._fields["notes"]

        self.assertEqual(field.type, "html")
        self.assertFalse(field.tracking)
