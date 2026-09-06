from datetime import timedelta

from odoo import fields

from .test_call_followup_ux import TestCodestraCrmCallFollowupUx


class TestCodestraCrmCallFollowupUxHardening(
    TestCodestraCrmCallFollowupUx
):
    def test_due_snooze_is_released_exactly_once(self):
        self.followup._write_from_workflow(
            {
                "snoozed_until": (
                    fields.Datetime.now() - timedelta(minutes=1)
                ),
                "snooze_count": 1,
            }
        )
        model = self.env["codestra.crm.call.followup"]

        first = model._cron_release_snoozed_followups()
        second = model._cron_release_snoozed_followups()

        self.assertGreaterEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertFalse(self.followup.snoozed_until)
        self.assertTrue(self.followup.last_popup_released_at)
