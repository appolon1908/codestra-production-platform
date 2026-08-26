from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


EVENT_VERSION = "1.0"
DEFAULT_BATCH_SIZE = 10
MAX_BATCH_SIZE = 50
MAX_RESPONSE_BYTES = 65_536
MANUAL_RETRY_ATTEMPTS = 3
LEASE_TIMEOUT_MINUTES = 5

EVENT_TYPE_SELECTION = [
    ("post_call.completed", "Post-call Completed"),
    ("callback.scheduled", "Callback Scheduled"),
    ("appointment.scheduled", "Appointment Scheduled"),
    ("post_call.email_queued", "Post-call Email Queued"),
    ("calendar.rescheduled", "Calendar Rescheduled"),
    ("calendar.cancelled", "Calendar Cancelled"),
]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so credentials cannot be forwarded to another host."""

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        return None


class CodestraCrmCallFollowupOutbox(models.Model):
    _name = "codestra.crm.call.followup.outbox"
    _description = "CRM Call Follow-up Automation Outbox"
    _order = "priority desc, next_attempt_at asc, id asc"
    _rec_name = "event_id"

    event_id = fields.Char(required=True, readonly=True, index=True, copy=False)
    event_type = fields.Selection(
        EVENT_TYPE_SELECTION, required=True, readonly=True, index=True
    )
    event_version = fields.Char(
        required=True, readonly=True, default=EVENT_VERSION
    )
    occurred_at = fields.Datetime(required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    followup_id = fields.Many2one(
        "codestra.crm.call.followup",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    calendar_event_id = fields.Many2one(
        "calendar.event", readonly=True, index=True, ondelete="set null"
    )
    correlation_id = fields.Char(readonly=True, index=True)
    idempotency_key = fields.Char(
        required=True, readonly=True, index=True, copy=False
    )
    payload_json = fields.Json(required=True, readonly=True, copy=False)
    payload_sha256 = fields.Char(required=True, readonly=True, copy=False)

    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("retry", "Retry Scheduled"),
            ("delivered", "Delivered"),
            ("dead", "Dead Letter"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    priority = fields.Integer(default=10, readonly=True, index=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    max_attempts = fields.Integer(default=8, readonly=True)
    manual_retry_count = fields.Integer(default=0, readonly=True)
    next_attempt_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    locked_at = fields.Datetime(readonly=True, index=True)
    lease_token = fields.Char(readonly=True, index=True)
    delivered_at = fields.Datetime(readonly=True, index=True)
    last_http_status = fields.Integer(readonly=True)
    response_body_sha256 = fields.Char(readonly=True)
    last_error = fields.Char(readonly=True)

    _event_id_unique = models.Constraint(
        "UNIQUE(event_id)", "Automation event IDs must be unique."
    )
    _idempotency_key_unique = models.Constraint(
        "UNIQUE(idempotency_key)",
        "Automation idempotency keys must be unique.",
    )
    _attempt_count_non_negative = models.Constraint(
        "CHECK(attempt_count >= 0)",
        "Automation attempt counts cannot be negative.",
    )
    _manual_retry_count_non_negative = models.Constraint(
        "CHECK(manual_retry_count >= 0)",
        "Automation manual retry counts cannot be negative.",
    )
    _max_attempts_positive = models.Constraint(
        "CHECK(max_attempts > 0)",
        "Automation retry budgets must be positive.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("codestra_outbox_internal"):
            raise AccessError(
                _("Automation events can be created only by the workflow.")
            )
        return super().create(vals_list)

    def write(self, values):
        raise AccessError(
            _("Automation evidence is changed only by the delivery worker.")
        )

    def unlink(self):
        raise AccessError(_("Automation evidence cannot be deleted."))

    def _write_delivery(self, values):
        return super().write(values)

    def _write_if_claimed(self, values):
        """Update a claimed row only while this worker still owns its lease."""
        self.ensure_one()
        expected_token = self.lease_token
        if not expected_token:
            return False
        self.env.cr.execute(
            f"""
                SELECT state, lease_token
                  FROM {self._table}
                 WHERE id = %s
                 FOR UPDATE
            """,
            [self.id],
        )
        row = self.env.cr.fetchone()
        if not row or row[0] != "processing" or row[1] != expected_token:
            self.invalidate_recordset(["state", "lease_token", "locked_at"])
            return False
        self._write_delivery(values)
        return True

    @api.model
    def _canonical_payload(self, payload):
        return json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @api.model
    def _payload_sha256(self, payload):
        return hashlib.sha256(
            self._canonical_payload(payload).encode("utf-8")
        ).hexdigest()

    @api.model
    def _enqueue(
        self,
        *,
        event_type,
        followup,
        payload,
        idempotency_key,
        calendar_event=False,
        occurred_at=False,
    ):
        if event_type not in dict(EVENT_TYPE_SELECTION):
            raise ValidationError(_("Unsupported automation event type."))
        followup.ensure_one()
        occurred_at = occurred_at or fields.Datetime.now()
        payload_sha256 = self._payload_sha256(payload)
        values = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "event_version": EVENT_VERSION,
            "occurred_at": occurred_at,
            "company_id": followup.company_id.id,
            "followup_id": followup.id,
            "calendar_event_id": (
                calendar_event.id if calendar_event else False
            ),
            "correlation_id": followup.correlation_id or False,
            "idempotency_key": idempotency_key,
            "payload_json": payload,
            "payload_sha256": payload_sha256,
            "state": "pending",
            "next_attempt_at": fields.Datetime.now(),
        }
        model = self.sudo().with_context(codestra_outbox_internal=True)
        try:
            with self.env.cr.savepoint():
                return model.create(values)
        except IntegrityError:
            existing = self.sudo().search(
                [("idempotency_key", "=", idempotency_key)], limit=1
            )
            if not existing:
                raise
            if (
                existing.event_type != event_type
                or existing.payload_sha256 != payload_sha256
            ):
                raise ValidationError(
                    _(
                        "The automation idempotency key already exists with "
                        "a different immutable event."
                    )
                )
            return existing

    @api.model
    def _followup_payload(self, followup):
        followup.ensure_one()
        return {
            "followup_id": followup.id,
            "source_event_id": followup.event_id,
            "call_id": followup.call_id or False,
            "company_id": followup.company_id.id,
            "agent_user_id": followup.agent_id.id,
            "lead_id": followup.lead_id.id or False,
            "partner_id": followup.partner_id.id or False,
            "call_ended_at": (
                fields.Datetime.to_string(followup.ended_at)
                if followup.ended_at
                else False
            ),
            "duration_seconds": followup.duration_seconds,
            "disposition": followup.disposition or False,
            "schedule_kind": followup.schedule_kind,
            "callback_at": (
                fields.Datetime.to_string(followup.callback_at)
                if followup.callback_at
                else False
            ),
            "duration_minutes": followup.duration_minutes,
            "calendar_event_id": followup.calendar_event_id.id or False,
            "mail_id": followup.mail_id.id or False,
        }

    @api.model
    def enqueue_followup_events(self, followup):
        followup.ensure_one()
        payload = self._followup_payload(followup)
        prefix = (
            f"call-followup:{followup.company_id.id}:{followup.event_id}"
        )
        events = [
            self._enqueue(
                event_type="post_call.completed",
                followup=followup,
                payload=payload,
                idempotency_key=f"{prefix}:post_call.completed:v1",
            )
        ]
        if followup.schedule_kind in {"callback", "appointment"}:
            event_type = f"{followup.schedule_kind}.scheduled"
            events.append(
                self._enqueue(
                    event_type=event_type,
                    followup=followup,
                    payload=payload,
                    idempotency_key=f"{prefix}:{event_type}:v1",
                    calendar_event=followup.calendar_event_id,
                )
            )
        if followup.mail_id:
            events.append(
                self._enqueue(
                    event_type="post_call.email_queued",
                    followup=followup,
                    payload=payload,
                    idempotency_key=(
                        f"{prefix}:post_call.email_queued:v1"
                    ),
                )
            )
        return events

    @api.model
    def enqueue_calendar_event(self, event, event_type):
        event.ensure_one()
        followup = event.codestra_call_followup_id
        if not followup:
            return self.browse()
        if event_type not in {
            "calendar.rescheduled",
            "calendar.cancelled",
        }:
            raise ValidationError(
                _("Unsupported calendar automation event type.")
            )
        payload = self._followup_payload(followup)
        payload.update(
            {
                "calendar_event_id": event.id,
                "calendar_start": (
                    fields.Datetime.to_string(event.start)
                    if event.start
                    else False
                ),
                "calendar_stop": (
                    fields.Datetime.to_string(event.stop)
                    if event.stop
                    else False
                ),
                "calendar_active": event.active,
            }
        )
        mutation_sha256 = self._payload_sha256(payload)
        return self._enqueue(
            event_type=event_type,
            followup=followup,
            payload=payload,
            idempotency_key=(
                f"calendar:{event.id}:{event_type}:v1:{mutation_sha256}"
            ),
            calendar_event=event,
        )

    @api.model
    def _parameter(self, key, default=False):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(key, default)
        )

    @api.model
    def _enabled(self):
        return str(
            self._parameter(
                "codestra.call_followup_automation.enabled", "False"
            )
        ).strip().lower() in {"1", "true", "yes", "on"}

    @api.model
    def _read_secret_file(self, parameter_key, minimum_length=16):
        path_value = str(
            self._parameter(parameter_key, "") or ""
        ).strip()
        if not path_value:
            raise ValidationError(
                _("A required automation secret file is not configured.")
            )
        path = Path(path_value)
        if not path.is_file():
            raise ValidationError(
                _("A required automation secret file is not a regular file.")
            )
        try:
            data = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(
                _("A required automation secret file cannot be read.")
            ) from exc
        secret = data.strip()
        if not minimum_length <= len(secret) <= 4096:
            raise ValidationError(
                _("A required automation secret has an invalid length.")
            )
        return secret

    @api.model
    def _delivery_config(self):
        target_url = str(
            self._parameter(
                "codestra.call_followup_automation.target_url", ""
            )
            or ""
        ).strip()
        tenant_id = str(
            self._parameter(
                "codestra.call_followup_automation.tenant_id", ""
            )
            or ""
        ).strip()
        parsed = urllib.parse.urlparse(target_url)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        allow_loopback = str(
            self._parameter(
                "codestra.call_followup_automation.allow_insecure_loopback",
                "False",
            )
        ).strip().lower() in {"1", "true", "yes", "on"}
        allowed_hosts = {
            host.strip().rstrip(".").lower()
            for host in str(
                self._parameter(
                    "codestra.call_followup_automation.allowed_hosts", ""
                )
                or ""
            ).split(",")
            if host.strip()
        }
        loopback = hostname in {"127.0.0.1", "::1", "localhost"}

        if not parsed.netloc or not hostname or not tenant_id:
            raise ValidationError(
                _("The automation target and tenant are required.")
            )
        if parsed.username or parsed.password or parsed.fragment:
            raise ValidationError(
                _("The automation target URL cannot contain credentials or a fragment.")
            )
        if "*" in allowed_hosts:
            raise ValidationError(
                _("Wildcard automation hosts are not allowed.")
            )
        if loopback:
            if not allow_loopback or parsed.scheme not in {"http", "https"}:
                raise ValidationError(
                    _("Loopback automation targets require the explicit test-only flag.")
                )
        else:
            if parsed.scheme != "https":
                raise ValidationError(
                    _("The automation target must use HTTPS.")
                )
            if hostname not in allowed_hosts:
                raise ValidationError(
                    _("The automation target host is not on the approved allowlist.")
                )

        try:
            timeout = float(
                self._parameter(
                    "codestra.call_followup_automation.timeout_seconds",
                    "5",
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("The automation timeout is invalid.")
            ) from exc
        timeout = max(1.0, min(timeout, 30.0))
        return {
            "target_url": target_url,
            "target_host": hostname,
            "tenant_id": tenant_id,
            "timeout": timeout,
            "api_key": self._read_secret_file(
                "codestra.call_followup_automation.api_key_file",
                minimum_length=16,
            ),
            "webhook_secret": self._read_secret_file(
                "codestra.call_followup_automation.webhook_secret_file",
                minimum_length=32,
            ),
        }

    def _envelope(self, config):
        self.ensure_one()
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": fields.Datetime.to_string(self.occurred_at),
            "tenant_id": config["tenant_id"],
            "company_id": self.company_id.id,
            "correlation_id": self.correlation_id or False,
            "idempotency_key": self.idempotency_key,
            "aggregate": {
                "type": "crm_call_followup",
                "id": self.followup_id.id,
            },
            "payload": self.payload_json,
            "metadata": {
                "source": "odoo",
                "delivery_attempt": self.attempt_count + 1,
            },
        }

    def _post_event(self, config):
        self.ensure_one()
        raw = json.dumps(
            self._envelope(config),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        canonical = b"\n".join(
            (
                timestamp.encode("ascii"),
                self.event_id.encode("utf-8"),
                config["tenant_id"].encode("utf-8"),
                raw,
            )
        )
        signature = hmac.new(
            config["webhook_secret"].encode("utf-8"),
            canonical,
            hashlib.sha256,
        ).hexdigest()
        request = urllib.request.Request(
            config["target_url"],
            data=raw,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config['api_key']}",
                "Idempotency-Key": self.idempotency_key,
                "User-Agent": "codestra-odoo-call-followup/1.0",
                "X-Event-Id": self.event_id,
                "X-Correlation-Id": (
                    self.correlation_id or self.event_id
                ),
                "X-Tenant-Id": config["tenant_id"],
                "X-Timestamp": timestamp,
                "X-Signature": f"sha256={signature}",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=config["timeout"]) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValidationError(
                    _("The automation response exceeded the size limit.")
                )
            return {
                "status": int(response.status),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }

    def _retry_delay_seconds(self, attempt):
        base = min(3600, 30 * (2 ** max(0, attempt - 1)))
        jitter = (self.id * 17 + attempt * 29) % 31
        return base + jitter

    def _record_success(self, result):
        self.ensure_one()
        return self._write_if_claimed(
            {
                "state": "delivered",
                "attempt_count": self.attempt_count + 1,
                "delivered_at": fields.Datetime.now(),
                "locked_at": False,
                "lease_token": False,
                "last_http_status": result["status"],
                "response_body_sha256": result["body_sha256"],
                "last_error": False,
            }
        )

    def _record_failure(
        self,
        *,
        status=False,
        error_code="delivery_failed",
        permanent=False,
    ):
        self.ensure_one()
        attempt = self.attempt_count + 1
        exhausted = attempt >= self.max_attempts
        state = "dead" if permanent or exhausted else "retry"
        values = {
            "state": state,
            "attempt_count": attempt,
            "locked_at": False,
            "lease_token": False,
            "last_http_status": status or False,
            "last_error": str(error_code)[:500],
        }
        if state == "retry":
            values["next_attempt_at"] = (
                fields.Datetime.now()
                + timedelta(
                    seconds=self._retry_delay_seconds(attempt)
                )
            )
        return self._write_if_claimed(values)

    @api.model
    def _claim_due(self, batch_size):
        now = fields.Datetime.now()
        stale_before = now - timedelta(minutes=LEASE_TIMEOUT_MINUTES)
        self.env.cr.execute(
            f"""
                SELECT id
                  FROM {self._table}
                 WHERE (
                       state IN ('pending', 'retry')
                       AND next_attempt_at <= %s
                       AND (locked_at IS NULL OR locked_at < %s)
                 ) OR (
                       state = 'processing'
                       AND locked_at < %s
                 )
                 ORDER BY priority DESC, next_attempt_at ASC, id ASC
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            """,
            [now, stale_before, stale_before, batch_size],
        )
        records = self.browse([row[0] for row in self.env.cr.fetchall()])
        for record in records:
            record._write_delivery(
                {
                    "state": "processing",
                    "locked_at": now,
                    "lease_token": str(uuid.uuid4()),
                }
            )
        return records

    @api.model
    def _cron_process_outbox(self, batch_size=DEFAULT_BATCH_SIZE):
        if not self._enabled():
            return 0
        try:
            batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
        except (TypeError, ValueError):
            batch_size = DEFAULT_BATCH_SIZE
        config = self._delivery_config()
        records = self._claim_due(batch_size)
        for record in records:
            try:
                result = record._post_event(config)
                record._record_success(result)
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                permanent = (
                    300 <= status < 400
                    or (
                        400 <= status < 500
                        and status not in {408, 429}
                    )
                )
                record._record_failure(
                    status=status,
                    error_code=f"http_{status}",
                    permanent=permanent,
                )
            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
            ):
                record._record_failure(error_code="transport_error")
            except ValidationError:
                record._record_failure(
                    error_code="response_validation_error",
                    permanent=True,
                )
            except Exception:
                record._record_failure(
                    error_code="unexpected_delivery_error"
                )
        return len(records)

    def action_retry_now(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(
                _("Only a call-follow-up manager may retry automation.")
            )
        for record in self:
            if record.state not in {"retry", "dead"}:
                raise ValidationError(
                    _("Only retry or dead-letter events can be retried.")
                )
            record._write_delivery(
                {
                    "state": "pending",
                    "max_attempts": max(
                        record.max_attempts,
                        record.attempt_count + MANUAL_RETRY_ATTEMPTS,
                    ),
                    "manual_retry_count": record.manual_retry_count + 1,
                    "next_attempt_at": fields.Datetime.now(),
                    "locked_at": False,
                    "lease_token": False,
                    "last_error": False,
                }
            )
        return True

    def action_mark_dead(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(
                _("Only a call-follow-up manager may dead-letter automation.")
            )
        for record in self:
            if record.state not in {"pending", "retry"}:
                raise ValidationError(
                    _("Only pending or retry events can be manually dead-lettered.")
                )
        self._write_delivery(
            {
                "state": "dead",
                "locked_at": False,
                "lease_token": False,
                "last_error": "manually_dead_lettered",
            }
        )
        return True

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

    @api.model
    def get_automation_status(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(
                _("Only a call-follow-up manager may view automation status.")
            )
        return {
            "enabled": self._enabled(),
            "counts": {
                state: self.search_count(
                    [
                        ("company_id", "in", self.env.companies.ids),
                        ("state", "=", state),
                    ]
                )
                for state in [
                    "pending",
                    "processing",
                    "retry",
                    "delivered",
                    "dead",
                ]
            },
        }
