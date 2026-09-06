from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CodestraCrmCallFollowupAnalyticsApi(models.AbstractModel):
    _name = "codestra.crm.call.followup.analytics.api"
    _description = "CRM Call Follow-up Analytics API"

    @api.model
    def _require_manager(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(_("Call follow-up manager access is required."))

    @api.model
    def capabilities_v1(self):
        return {
            "api_version": "1.0",
            "features": [
                "read-only-operational-view",
                "summary-kpis",
                "agent-scorecards",
                "completion-sla",
                "callback-and-appointment-rates",
                "email-queue-health",
            ],
            "default_window_days": 30,
        }

    @api.model
    def _scope(self, date_from=None, date_to=None, company_ids=None, agent_ids=None):
        self._require_manager()
        today = fields.Date.context_today(self)
        try:
            date_to = fields.Date.to_date(date_to) if date_to else today
            date_from = (
                fields.Date.to_date(date_from)
                if date_from
                else date_to - timedelta(days=29)
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("date_from and date_to must be valid dates.")) from exc
        if date_from > date_to:
            raise ValidationError(_("date_from cannot be after date_to."))
        allowed = set(self.env.user.company_ids.ids)
        requested = set(int(item) for item in (company_ids or allowed))
        companies = sorted(allowed & requested)
        if not companies:
            raise AccessError(_("No permitted company was selected."))
        agents = sorted({int(item) for item in (agent_ids or [])})
        return date_from, date_to, companies, agents

    @api.model
    def _where(self, date_from, date_to, company_ids, agent_ids):
        user_timezone = pytz.timezone(self.env.user.tz or "UTC")
        local_start = user_timezone.localize(datetime.combine(date_from, time.min))
        local_end = user_timezone.localize(
            datetime.combine(date_to + timedelta(days=1), time.min)
        )
        utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
        clauses = ["company_id = ANY(%s)", "ended_at >= %s", "ended_at < %s"]
        params = [company_ids, utc_start, utc_end]
        if agent_ids:
            clauses.append("agent_id = ANY(%s)")
            params.append(agent_ids)
        return " AND ".join(clauses), params

    @api.model
    def _flush_report_sources(self):
        # The report is a SQL view, so Odoo cannot infer the source models that
        # must be flushed before a raw aggregate query in the same transaction.
        self.env["codestra.crm.call.followup"].flush_model()
        self.env["mail.mail"].flush_model()

    @api.model
    def summary_v1(self, date_from=None, date_to=None, company_ids=None, agent_ids=None):
        date_from, date_to, companies, agents = self._scope(
            date_from, date_to, company_ids, agent_ids
        )
        where, params = self._where(date_from, date_to, companies, agents)
        self._flush_report_sources()
        self.env.cr.execute(
            f"""
                SELECT
                    COUNT(*)::integer AS total_calls,
                    COUNT(*) FILTER (WHERE is_pending)::integer AS pending,
                    COUNT(*) FILTER (WHERE is_completed)::integer AS completed,
                    COUNT(*) FILTER (WHERE is_cancelled)::integer AS cancelled,
                    COUNT(*) FILTER (WHERE is_callback)::integer AS callbacks,
                    COUNT(*) FILTER (WHERE is_appointment)::integer AS appointments,
                    COUNT(*) FILTER (WHERE email_state = 'outgoing')::integer AS email_queued,
                    COUNT(*) FILTER (WHERE email_state = 'sent')::integer AS email_sent,
                    COUNT(*) FILTER (WHERE email_state = 'cancel')::integer AS email_cancelled,
                    COUNT(*) FILTER (WHERE email_failed)::integer AS email_failed,
                    COUNT(*) FILTER (WHERE pending_over_10_minutes)::integer AS pending_over_10,
                    ROUND(AVG(completion_minutes) FILTER (WHERE completion_minutes IS NOT NULL)::numeric, 2) AS avg_completion_minutes,
                    ROUND(AVG(duration_seconds)::numeric, 2) AS avg_call_seconds,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE completed_within_5_minutes)
                        / NULLIF(COUNT(*) FILTER (WHERE is_completed), 0),
                        2
                    ) AS completed_within_5_rate,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE is_callback)
                        / NULLIF(COUNT(*), 0),
                        2
                    ) AS callback_rate,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE is_appointment)
                        / NULLIF(COUNT(*), 0),
                        2
                    ) AS appointment_rate
                FROM codestra_crm_call_followup_report
                WHERE {where}
            """,
            params,
        )
        columns = [description.name for description in self.env.cr.description]
        values = self.env.cr.fetchone()
        metrics = dict(zip(columns, values))
        for key, value in list(metrics.items()):
            if hasattr(value, "as_tuple"):
                metrics[key] = float(value)
        return {
            "api_version": "1.0",
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "company_ids": companies,
            "agent_ids": agents,
            "metrics": metrics,
        }

    @api.model
    def agent_scorecards_v1(
        self,
        date_from=None,
        date_to=None,
        company_ids=None,
        agent_ids=None,
        limit=100,
    ):
        date_from, date_to, companies, agents = self._scope(
            date_from, date_to, company_ids, agent_ids
        )
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 100
        where, params = self._where(date_from, date_to, companies, agents)
        self._flush_report_sources()
        self.env.cr.execute(
            f"""
                SELECT
                    agent_id,
                    COUNT(*)::integer AS total_calls,
                    COUNT(*) FILTER (WHERE is_pending)::integer AS pending,
                    COUNT(*) FILTER (WHERE is_completed)::integer AS completed,
                    COUNT(*) FILTER (WHERE is_callback)::integer AS callbacks,
                    COUNT(*) FILTER (WHERE is_appointment)::integer AS appointments,
                    COUNT(*) FILTER (WHERE email_failed)::integer AS email_failed,
                    ROUND(AVG(completion_minutes) FILTER (WHERE completion_minutes IS NOT NULL)::numeric, 2) AS avg_completion_minutes,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE completed_within_5_minutes)
                        / NULLIF(COUNT(*) FILTER (WHERE is_completed), 0),
                        2
                    ) AS completed_within_5_rate
                FROM codestra_crm_call_followup_report
                WHERE {where}
                GROUP BY agent_id
                ORDER BY total_calls DESC, agent_id
                LIMIT %s
            """,
            params + [limit],
        )
        columns = [description.name for description in self.env.cr.description]
        rows = [dict(zip(columns, row)) for row in self.env.cr.fetchall()]
        users = self.env["res.users"].browse([row["agent_id"] for row in rows]).exists()
        names = {user.id: user.display_name for user in users}
        for row in rows:
            row["agent_name"] = names.get(row["agent_id"], _("Unknown agent"))
            for key, value in list(row.items()):
                if hasattr(value, "as_tuple"):
                    row[key] = float(value)
        return {
            "api_version": "1.0",
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "company_ids": companies,
            "items": rows,
        }
