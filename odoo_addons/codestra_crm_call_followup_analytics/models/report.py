from odoo import fields, models, tools


class CodestraCrmCallFollowupReport(models.Model):
    _name = "codestra.crm.call.followup.report"
    _description = "CRM Call Follow-up Operational Analysis"
    _auto = False
    _rec_name = "name"
    _order = "ended_at desc, id desc"

    followup_id = fields.Many2one("codestra.crm.call.followup", readonly=True)
    name = fields.Char(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    agent_id = fields.Many2one("res.users", readonly=True)
    lead_id = fields.Many2one("crm.lead", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    ended_at = fields.Datetime(readonly=True)
    popup_completed_at = fields.Datetime(readonly=True)
    callback_at = fields.Datetime(readonly=True)
    duration_seconds = fields.Integer(readonly=True)
    completion_minutes = fields.Float(readonly=True)
    pending_age_minutes = fields.Float(readonly=True)
    callback_lead_minutes = fields.Float(readonly=True)
    state = fields.Selection(
        [
            ("pending", "Needs Follow-up"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        readonly=True,
    )
    disposition = fields.Char(readonly=True)
    schedule_kind = fields.Selection(
        [
            ("none", "No Schedule"),
            ("callback", "Callback"),
            ("appointment", "Appointment"),
        ],
        readonly=True,
    )
    calendar_event_id = fields.Many2one("calendar.event", readonly=True)
    send_post_call_email = fields.Boolean(readonly=True)
    mail_id = fields.Many2one("mail.mail", readonly=True)
    email_state = fields.Selection(
        [
            ("none", "No Email"),
            ("outgoing", "Queued"),
            ("sent", "Sent"),
            ("received", "Received"),
            ("exception", "Failed"),
            ("cancel", "Cancelled"),
        ],
        readonly=True,
    )
    completion_bucket = fields.Selection(
        [
            ("pending", "Pending"),
            ("under_2", "Under 2 minutes"),
            ("under_5", "2–5 minutes"),
            ("under_10", "5–10 minutes"),
            ("over_10", "Over 10 minutes"),
            ("cancelled", "Cancelled"),
        ],
        readonly=True,
    )
    call_count = fields.Integer(readonly=True)
    is_pending = fields.Boolean(readonly=True)
    is_completed = fields.Boolean(readonly=True)
    is_cancelled = fields.Boolean(readonly=True)
    is_scheduled = fields.Boolean(readonly=True)
    is_callback = fields.Boolean(readonly=True)
    is_appointment = fields.Boolean(readonly=True)
    has_calendar_event = fields.Boolean(readonly=True)
    has_email = fields.Boolean(readonly=True)
    email_failed = fields.Boolean(readonly=True)
    completed_within_5_minutes = fields.Boolean(readonly=True)
    pending_over_10_minutes = fields.Boolean(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            f"""
                CREATE VIEW {self._table} AS (
                    SELECT
                        f.id AS id,
                        f.id AS followup_id,
                        f.name AS name,
                        f.company_id AS company_id,
                        f.agent_id AS agent_id,
                        f.lead_id AS lead_id,
                        f.partner_id AS partner_id,
                        f.ended_at AS ended_at,
                        f.popup_completed_at AS popup_completed_at,
                        f.callback_at AS callback_at,
                        f.duration_seconds AS duration_seconds,
                        CASE
                            WHEN f.popup_completed_at IS NOT NULL
                            THEN GREATEST(0, EXTRACT(EPOCH FROM (f.popup_completed_at - f.ended_at)) / 60.0)
                            ELSE NULL
                        END AS completion_minutes,
                        CASE
                            WHEN f.state = 'pending'
                            THEN GREATEST(0, EXTRACT(EPOCH FROM ((NOW() AT TIME ZONE 'UTC') - f.ended_at)) / 60.0)
                            ELSE NULL
                        END AS pending_age_minutes,
                        CASE
                            WHEN f.callback_at IS NOT NULL
                            THEN EXTRACT(EPOCH FROM (f.callback_at - f.ended_at)) / 60.0
                            ELSE NULL
                        END AS callback_lead_minutes,
                        f.state AS state,
                        f.disposition AS disposition,
                        f.schedule_kind AS schedule_kind,
                        f.calendar_event_id AS calendar_event_id,
                        f.send_post_call_email AS send_post_call_email,
                        f.mail_id AS mail_id,
                        COALESCE(m.state, 'none') AS email_state,
                        CASE
                            WHEN f.state = 'pending' THEN 'pending'
                            WHEN f.state = 'cancelled' THEN 'cancelled'
                            WHEN EXTRACT(EPOCH FROM (f.popup_completed_at - f.ended_at)) / 60.0 <= 2 THEN 'under_2'
                            WHEN EXTRACT(EPOCH FROM (f.popup_completed_at - f.ended_at)) / 60.0 <= 5 THEN 'under_5'
                            WHEN EXTRACT(EPOCH FROM (f.popup_completed_at - f.ended_at)) / 60.0 <= 10 THEN 'under_10'
                            ELSE 'over_10'
                        END AS completion_bucket,
                        1 AS call_count,
                        (f.state = 'pending') AS is_pending,
                        (f.state = 'completed') AS is_completed,
                        (f.state = 'cancelled') AS is_cancelled,
                        (f.schedule_kind <> 'none' AND f.callback_at IS NOT NULL) AS is_scheduled,
                        (f.schedule_kind = 'callback') AS is_callback,
                        (f.schedule_kind = 'appointment') AS is_appointment,
                        (f.calendar_event_id IS NOT NULL) AS has_calendar_event,
                        (f.mail_id IS NOT NULL) AS has_email,
                        (m.state = 'exception') AS email_failed,
                        (
                            f.state = 'completed'
                            AND f.popup_completed_at IS NOT NULL
                            AND EXTRACT(EPOCH FROM (f.popup_completed_at - f.ended_at)) / 60.0 <= 5
                        ) AS completed_within_5_minutes,
                        (
                            f.state = 'pending'
                            AND EXTRACT(EPOCH FROM ((NOW() AT TIME ZONE 'UTC') - f.ended_at)) / 60.0 > 10
                        ) AS pending_over_10_minutes
                    FROM codestra_crm_call_followup f
                    LEFT JOIN mail_mail m ON m.id = f.mail_id
                )
            """
        )
