from __future__ import annotations

from datetime import timedelta
import logging

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.fields import Command
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)

JOB_TYPES = [
    ("pending_sla", "Pending post-call SLA"),
    ("missed_callback", "Missed callback"),
    ("reminder_health", "Calendar reminder health"),
]


class CodestraCrmCallFollowupJob(models.Model):
    _name = "codestra.crm.call.followup.job"
    _description = "CRM Call Follow-up Durable Automation Job"
    _order = "next_attempt_at, id"

    name = fields.Char(required=True, readonly=True)
    job_type = fields.Selection(JOB_TYPES, required=True, readonly=True, index=True)
    followup_id = fields.Many2one(
        "codestra.crm.call.followup",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="followup_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    policy_id = fields.Many2one(
        "codestra.crm.call.followup.policy",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
        check_company=True,
    )
    idempotency_key = fields.Char(required=True, readonly=True, index=True, copy=False)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("running", "Running"),
            ("retry", "Retry"),
            ("done", "Done"),
            ("dead", "Dead letter"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    attempt_count = fields.Integer(default=0, readonly=True)
    max_attempts = fields.Integer(required=True, readonly=True, default=5)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    locked_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    last_error = fields.Char(readonly=True)
    payload_json = fields.Json(default=dict, readonly=True)
    activity_id = fields.Many2one("mail.activity", readonly=True, ondelete="set null")

    _idempotency_unique = models.Constraint(
        "UNIQUE(idempotency_key)",
        "A call follow-up automation job with this idempotency key already exists.",
    )

    @api.model
    def _enqueue(self, policy, followup, job_type, idempotency_key, payload=None):
        existing = self.sudo().search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            completed_without_effect = (
                existing.state == "done"
                and not existing.activity_id
                and (
                    (job_type == "pending_sla" and not followup.automation_pending_sla_at)
                    or (job_type == "missed_callback" and not followup.automation_missed_callback_at)
                    or (job_type == "reminder_health" and not followup.automation_reminders_repaired_at)
                )
            )
            if completed_without_effect:
                existing.write({"state": "pending", "completed_at": False,
                                "next_attempt_at": fields.Datetime.now(), "last_error": False})
            return existing, False
        values = {
            "name": _("%s — %s") % (dict(JOB_TYPES)[job_type], followup.display_name),
            "job_type": job_type,
            "followup_id": followup.id,
            "policy_id": policy.id,
            "idempotency_key": idempotency_key,
            "max_attempts": policy.max_attempts,
            "next_attempt_at": fields.Datetime.now(),
            "payload_json": payload or {},
        }
        created = False
        try:
            with self.env.cr.savepoint():
                job = self.sudo().create(values)
                created = True
        except IntegrityError:
            job = self.sudo().search([("idempotency_key", "=", idempotency_key)], limit=1)
            if not job:
                raise
        return job, created

    @api.model
    def _cron_enqueue_due_jobs(self, company_ids=None, limit_per_policy=500):
        policy_domain = [("active", "=", True)]
        if company_ids is not None:
            if not company_ids:
                return 0
            policy_domain.append(("company_id", "in", company_ids))
        policies = self.env["codestra.crm.call.followup.policy"].sudo().search(policy_domain)
        Followup = self.env["codestra.crm.call.followup"].sudo()
        now = fields.Datetime.now()
        created_count = 0

        def candidates(domain, order):
            offset = 0
            while True:
                batch = Followup.search(domain, order=order, limit=limit_per_policy,
                                        offset=offset)
                if not batch:
                    return
                yield from batch
                offset += len(batch)

        for policy in policies:
            if policy.create_pending_activity:
                cutoff = now - timedelta(minutes=policy.pending_sla_minutes)
                pending_domain = [
                        ("company_id", "=", policy.company_id.id),
                        ("state", "=", "pending"),
                        ("popup_completed_at", "=", False),
                        ("ended_at", "<=", cutoff),
                        ("automation_pending_sla_at", "=", False),
                    ]
                type_created = 0
                for followup in candidates(pending_domain, "ended_at, id"):
                    deadline = followup.ended_at + timedelta(
                        minutes=policy.pending_sla_minutes
                    )
                    occurrence = fields.Datetime.to_string(deadline)
                    _, created = self._enqueue(
                        policy,
                        followup,
                        "pending_sla",
                        f"pending-sla:{policy.id}:{followup.id}:{occurrence}",
                        {"effective_deadline": occurrence},
                    )
                    created_count += int(created)
                    type_created += int(created)
                    if type_created >= limit_per_policy:
                        break

            if policy.create_missed_callback_activity:
                callback_cutoff = now - timedelta(minutes=policy.callback_grace_minutes)
                missed_domain = [
                        ("company_id", "=", policy.company_id.id),
                        ("state", "=", "completed"),
                        ("schedule_kind", "!=", "none"),
                        ("callback_at", "!=", False),
                        ("callback_at", "<=", callback_cutoff),
                        ("callback_completed_at", "=", False),
                        ("automation_missed_callback_at", "=", False),
                    ]
                type_created = 0
                for followup in candidates(missed_domain, "callback_at, id"):
                    deadline = followup.callback_at + timedelta(
                        minutes=policy.callback_grace_minutes
                    )
                    occurrence = fields.Datetime.to_string(deadline)
                    _, created = self._enqueue(
                        policy,
                        followup,
                        "missed_callback",
                        f"missed-callback:{policy.id}:{followup.id}:{occurrence}",
                        {"effective_deadline": occurrence},
                    )
                    created_count += int(created)
                    type_created += int(created)
                    if type_created >= limit_per_policy:
                        break

            if policy.repair_calendar_reminders:
                scheduled_domain = [
                        ("company_id", "=", policy.company_id.id),
                        ("state", "=", "completed"),
                        ("calendar_event_id", "!=", False),
                        ("callback_at", ">", now),
                    ]
                required_notification = self.env.ref(
                    "codestra_crm_call_followup.calendar_alarm_prepare_30_minutes"
                )
                required_email = self.env.ref(
                    "codestra_crm_call_followup.calendar_alarm_email_15_minutes"
                )
                type_created = 0
                for followup in candidates(scheduled_domain, "callback_at, id"):
                    desired = {required_notification.id}
                    if followup.reminder_email_enabled:
                        desired.add(required_email.id)
                    if desired.issubset(set(followup.calendar_event_id.alarm_ids.ids)):
                        continue
                    event_version = fields.Datetime.to_string(
                        followup.calendar_event_id.write_date
                        or followup.calendar_event_id.create_date
                        or now
                    )
                    _, created = self._enqueue(
                        policy,
                        followup,
                        "reminder_health",
                        f"reminder-health:{policy.id}:{followup.id}:{event_version}",
                        {"calendar_event_id": followup.calendar_event_id.id},
                    )
                    created_count += int(created)
                    type_created += int(created)
                    if type_created >= limit_per_policy:
                        break
        return created_count

    @api.model
    def _cron_process_jobs(self, limit=100, company_ids=None):
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 100
        now = fields.Datetime.now()
        if company_ids is not None and not company_ids:
            return 0
        company_clause = ""
        params = [now]
        if company_ids is not None:
            company_clause = "AND company_id = ANY(%s)"
            params.append(company_ids)
        params.append(limit)
        self.env.cr.execute(
            f"""
                SELECT id
                  FROM {self._table}
                 WHERE state IN ('pending', 'retry')
                   AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                   {company_clause}
                 ORDER BY next_attempt_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            """,
            params,
        )
        jobs = self.sudo().browse([row[0] for row in self.env.cr.fetchall()])
        processed = 0
        for job in jobs:
            attempt = job.attempt_count + 1
            job.write(
                {
                    "state": "running",
                    "attempt_count": attempt,
                    "locked_at": now,
                    "last_error": False,
                }
            )
            try:
                with self.env.cr.savepoint():
                    applied = job._process_job()
                    if applied is False:
                        processed += 1
                        continue
                    job.write(
                        {
                            "state": "done",
                            "completed_at": fields.Datetime.now(),
                            "next_attempt_at": False,
                            "locked_at": False,
                        }
                    )
                    job.followup_id._write_from_workflow(
                        {"automation_last_job_at": fields.Datetime.now()}
                    )
                processed += 1
            except Exception as exc:  # durable boundary: retain and retry safely
                _logger.exception("Call follow-up automation job %s failed", job.id)
                dead = attempt >= job.max_attempts
                delay = min(60, job.policy_id.retry_base_minutes * (2 ** max(0, attempt - 1)))
                job.write(
                    {
                        "state": "dead" if dead else "retry",
                        "next_attempt_at": False
                        if dead
                        else fields.Datetime.now() + timedelta(minutes=delay),
                        "locked_at": False,
                        "last_error": f"{type(exc).__name__}: processing failed",
                    }
                )
                self.env.cr.execute(
                    """UPDATE codestra_crm_call_followup
                          SET automation_exception_count = COALESCE(automation_exception_count, 0) + 1,
                              automation_last_job_at = %s
                        WHERE id = %s""",
                    [fields.Datetime.now(), job.followup_id.id],
                )
                job.followup_id.invalidate_recordset(
                    ["automation_exception_count", "automation_last_job_at"]
                )
        return processed

    def _activity_owner(self):
        self.ensure_one()
        owner = self.policy_id.escalation_user_id
        if not owner or not owner.active or self.company_id not in owner.company_ids:
            owner = self.followup_id.agent_id
        if not owner or not owner.active or self.company_id not in owner.company_ids:
            owner = self.env["res.users"].sudo().search(
                [("active", "=", True), ("share", "=", False),
                 ("company_ids", "in", self.company_id.id)], limit=1,
            )
        if not owner:
            raise ValidationError(_("No active escalation owner can access this company."))
        return owner

    def _create_activity_once(self, summary, note):
        self.ensure_one()
        if self.activity_id:
            return self.activity_id
        activity = self.env["mail.activity"].sudo().create(
            {
                "res_model_id": self.env["ir.model"]._get_id(self.followup_id._name),
                "res_id": self.followup_id.id,
                "activity_type_id": self.policy_id.activity_type_id.id,
                "summary": summary,
                "note": note,
                "user_id": self._activity_owner().id,
                "date_deadline": fields.Date.context_today(self.followup_id),
            }
        )
        self.write({"activity_id": activity.id})
        return activity

    def _process_job(self):
        self.ensure_one()
        enabled = {
            "pending_sla": self.policy_id.create_pending_activity,
            "missed_callback": self.policy_id.create_missed_callback_activity,
            "reminder_health": self.policy_id.repair_calendar_reminders,
        }
        if not self.policy_id.active or not enabled[self.job_type]:
            return True
        handlers = {
            "pending_sla": self._process_pending_sla,
            "missed_callback": self._process_missed_callback,
            "reminder_health": self._process_reminder_health,
        }
        return handlers[self.job_type]()

    def _lock_followup(self):
        """Serialize an occurrence's final check and escalation mutation."""
        self.followup_id.flush_recordset()
        self.env.cr.execute(
            "SELECT id FROM codestra_crm_call_followup WHERE id = %s FOR UPDATE",
            [self.followup_id.id],
        )
        self.followup_id.invalidate_recordset()
        return self.followup_id

    def _defer_until(self, deadline):
        self.write(
            {
                "state": "pending",
                "next_attempt_at": deadline,
                "locked_at": False,
            }
        )
        return False

    def _process_pending_sla(self):
        followup = self._lock_followup()
        deadline = followup.ended_at + timedelta(
            minutes=self.policy_id.pending_sla_minutes
        )
        if (
            followup.state != "pending"
            or followup.popup_completed_at
            or followup.automation_pending_sla_at
        ):
            return True
        if deadline > fields.Datetime.now():
            return self._defer_until(deadline)
        self._create_activity_once(
            _("Post-call follow-up is overdue"),
            _("The assigned agent has not completed the call outcome within the configured SLA."),
        )
        followup._write_from_workflow(
            {"automation_pending_sla_at": fields.Datetime.now()}
        )
        return True

    def _process_missed_callback(self):
        followup = self._lock_followup()
        if (
            followup.state != "completed"
            or followup.schedule_kind == "none"
            or not followup.callback_at
            or followup.callback_completed_at
            or followup.automation_missed_callback_at
        ):
            return True
        deadline = followup.callback_at + timedelta(
            minutes=self.policy_id.callback_grace_minutes
        )
        if deadline > fields.Datetime.now():
            return self._defer_until(deadline)
        self._create_activity_once(
            _("Callback or appointment requires attention"),
            _("The scheduled client contact has passed its configured grace period."),
        )
        followup._write_from_workflow(
            {"automation_missed_callback_at": fields.Datetime.now()}
        )
        return True

    def _process_reminder_health(self):
        followup = self.followup_id
        event = followup.calendar_event_id
        if not event or not event.exists() or not event.active:
            return
        desired = {
            self.env.ref(
                "codestra_crm_call_followup.calendar_alarm_prepare_30_minutes"
            ).id
        }
        if followup.reminder_email_enabled:
            desired.add(
                self.env.ref(
                    "codestra_crm_call_followup.calendar_alarm_email_15_minutes"
                ).id
            )
        missing = desired - set(event.alarm_ids.ids)
        if missing:
            event.sudo().with_context(
                skip_codestra_followup_sync=True,
                mail_notify_force_send=False,
            ).write({"alarm_ids": [Command.link(alarm_id) for alarm_id in sorted(missing)]})
        followup._write_from_workflow(
            {"automation_reminders_repaired_at": fields.Datetime.now()}
        )
