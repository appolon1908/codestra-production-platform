from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError


POST_CALL_SLA_MINUTES = 10


class CodestraCrmCallFollowupReport(models.Model):
    _name = "codestra.crm.call.followup.report"
    _description = "CRM Call Follow-up Supervisor Report"
    _auto = False
    _rec_name = "followup_id"
    _order = "ended_at desc, id desc"

    followup_id = fields.Many2one(
        "codestra.crm.call.followup", readonly=True, index=True
    )
    company_id = fields.Many2one("res.company", readonly=True, index=True)
    agent_id = fields.Many2one("res.users", readonly=True, index=True)
    lead_id = fields.Many2one("crm.lead", readonly=True, index=True)
    partner_id = fields.Many2one("res.partner", readonly=True, index=True)

    ended_at = fields.Datetime(readonly=True, index=True)
    completed_at = fields.Datetime(readonly=True, index=True)
    callback_at = fields.Datetime(readonly=True, index=True)
    state = fields.Selection(
        [
            ("pending", "Needs Follow-up"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        readonly=True,
        index=True,
    )
    disposition = fields.Selection(
        [
            ("contacted", "Contacted"),
            ("callback", "Callback Requested"),
            ("appointment", "Appointment Booked"),
            ("sale", "Sale / Conversion"),
            ("no_answer", "No Answer"),
            ("voicemail", "Voicemail"),
            ("wrong_number", "Wrong Number"),
            ("do_not_call", "Do Not Call"),
            ("not_interested", "Not Interested"),
            ("other", "Other"),
        ],
        readonly=True,
        index=True,
    )
    priority = fields.Selection(
        [("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")],
        readonly=True,
        index=True,
    )
    customer_sentiment = fields.Selection(
        [("positive", "Positive"), ("neutral", "Neutral"), ("negative", "Negative")],
        readonly=True,
        index=True,
    )
    schedule_kind = fields.Selection(
        [("none", "No Schedule"), ("callback", "Callback"), ("appointment", "Appointment")],
        readonly=True,
        index=True,
    )
    call_direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound"), ("unknown", "Unknown")],
        readonly=True,
        index=True,
    )
    compliance_review_required = fields.Boolean(readonly=True, index=True)
    is_overdue = fields.Boolean(readonly=True, index=True)

    call_count = fields.Integer(readonly=True)
    scheduled_count = fields.Integer(readonly=True)
    compliance_count = fields.Integer(readonly=True)
    overdue_count = fields.Integer(readonly=True)
    email_queued_count = fields.Integer(readonly=True)
    call_duration_minutes = fields.Float(readonly=True, group_operator="avg")
    post_call_completion_minutes = fields.Float(readonly=True, group_operator="avg")
    pending_age_minutes = fields.Float(readonly=True, group_operator="avg")

    @api.model_create_multi
    def create(self, values_list):
        raise AccessError(_("Supervisor analytics is a read-only SQL view."))

    def write(self, values):
        raise AccessError(_("Supervisor analytics is a read-only SQL view."))

    def unlink(self):
        raise AccessError(_("Supervisor analytics is a read-only SQL view."))

    def action_open_followup(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.followup_id.display_name,
            "res_model": "codestra.crm.call.followup",
            "res_id": self.followup_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    f.id AS id,
                    f.id AS followup_id,
                    f.company_id,
                    f.agent_id,
                    f.lead_id,
                    f.partner_id,
                    f.ended_at,
                    f.completed_at,
                    f.callback_at,
                    f.state,
                    f.disposition,
                    f.priority,
                    f.customer_sentiment,
                    f.schedule_kind,
                    f.call_direction,
                    f.compliance_review_required,
                    (
                        f.state = 'pending'
                        AND f.popup_completed_at IS NULL
                        AND (f.snoozed_until IS NULL OR f.snoozed_until <= NOW())
                        AND f.ended_at <= NOW() - INTERVAL '{POST_CALL_SLA_MINUTES} minutes'
                    ) AS is_overdue,
                    1::integer AS call_count,
                    CASE WHEN f.schedule_kind <> 'none' THEN 1 ELSE 0 END::integer
                        AS scheduled_count,
                    CASE WHEN f.compliance_review_required THEN 1 ELSE 0 END::integer
                        AS compliance_count,
                    CASE
                        WHEN f.state = 'pending'
                         AND f.popup_completed_at IS NULL
                         AND (f.snoozed_until IS NULL OR f.snoozed_until <= NOW())
                         AND f.ended_at <= NOW() - INTERVAL '{POST_CALL_SLA_MINUTES} minutes'
                        THEN 1 ELSE 0
                    END::integer AS overdue_count,
                    CASE WHEN f.mail_id IS NOT NULL THEN 1 ELSE 0 END::integer
                        AS email_queued_count,
                    COALESCE(f.duration_seconds, 0)::double precision / 60.0
                        AS call_duration_minutes,
                    CASE
                        WHEN f.completed_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (f.completed_at - f.ended_at))
                             / 60.0
                        ELSE NULL
                    END::double precision AS post_call_completion_minutes,
                    CASE
                        WHEN f.state = 'pending'
                        THEN GREATEST(
                            0,
                            EXTRACT(EPOCH FROM (NOW() - f.ended_at)) / 60.0
                        )
                        ELSE 0
                    END::double precision AS pending_age_minutes
                FROM codestra_crm_call_followup f
            )
            """
        )
