from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import timezone

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .outbox import MAX_RESPONSE_BYTES, _NoRedirectHandler


MAX_SECRET_FILE_BYTES = 4096
MIDDLEWARE_SOURCE = "odoo"
WIRE_EVENT_TYPES = {
    "post_call.completed": "call_followup.completed",
    "callback.scheduled": "call_followup.callback_scheduled",
    "appointment.scheduled": "call_followup.appointment_scheduled",
    "post_call.email_queued": "call_followup.email_queued",
    "calendar.rescheduled": "call_followup.calendar_rescheduled",
    "calendar.cancelled": "call_followup.calendar_cancelled",
}
MIDDLEWARE_EVENT_STATES = {
    "queued",
    "retrying",
    "delivered",
    "dead_letter",
}


class CodestraCrmCallFollowupAutomationHardening(models.Model):
    """Harden secrets and the Odoo-to-Middleware delivery contract."""

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
        if parsed.path not in {
            "/api/v1/events/odoo",
            "/v1/events",
        }:
            raise ValidationError(
                _(
                    "The automation target URL must use an approved "
                    "Odoo event-ingress path."
                )
            )
        return super()._delivery_config()

    def _stable_correlation_id(self):
        self.ensure_one()
        return str(self.correlation_id or self.event_id)

    def _transport_event_id(self, attempt_number):
        """Return one deterministic transport nonce per durable attempt."""

        self.ensure_one()
        try:
            attempt_number = int(attempt_number)
            logical_event_id = uuid.UUID(str(self.event_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError(
                _("The automation event identity is invalid.")
            ) from exc
        if attempt_number < 1:
            raise ValidationError(
                _("The automation delivery attempt is invalid.")
            )
        return str(
            uuid.uuid5(
                logical_event_id,
                f"codestra-middleware-attempt:{attempt_number}",
            )
        )

    def _envelope(self, config, transport_event_id=None):
        """Build stable producer content with a separate transport nonce."""

        self.ensure_one()
        wire_event_type = WIRE_EVENT_TYPES.get(self.event_type)
        if not wire_event_type:
            raise ValidationError(
                _("The automation event type has no middleware mapping.")
            )
        transport_event_id = transport_event_id or self._transport_event_id(
            self.attempt_count + 1
        )
        occurred_at = fields.Datetime.to_datetime(self.occurred_at)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = occurred_at.astimezone(timezone.utc)
        return {
            "event_id": transport_event_id,
            "event_type": wire_event_type,
            "event_version": self.event_version,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "tenant_id": config["tenant_id"],
            "company_id": self.company_id.id,
            "correlation_id": self._stable_correlation_id(),
            "idempotency_key": self.idempotency_key,
            "aggregate": {
                "type": "crm_call_followup",
                "id": self.followup_id.id,
            },
            "payload": self.payload_json,
            "metadata": {
                "source": MIDDLEWARE_SOURCE,
                "logical_event_id": self.event_id,
            },
        }

    def _decode_receipt(self, body):
        self.ensure_one()
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValidationError(
                _("The automation response exceeded the size limit.")
            )
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                _("The automation response is not valid JSON.")
            ) from exc
        if not isinstance(value, dict):
            raise ValidationError(
                _("The automation response must be a JSON object.")
            )
        return value

    def _validated_receipt(
        self,
        *,
        status,
        body,
        attempt_number,
        transport_event_id,
    ):
        """Accept only a receipt bound to this logical delivery."""

        self.ensure_one()
        receipt = self._decode_receipt(body)
        body_sha256 = hashlib.sha256(body).hexdigest()

        if status == 409:
            if (
                receipt.get("error") != "replayed_event_id"
                or receipt.get("event_id") != transport_event_id
                or receipt.get("projection") is not None
            ):
                raise ValidationError(
                    _("The automation replay receipt is invalid.")
                )
            return {
                "status": status,
                "body_sha256": body_sha256,
                "receipt": "reconciled_replay",
            }

        if status not in {200, 202}:
            raise ValidationError(
                _("The automation response status is invalid.")
            )
        if receipt.get("correlation_id") != self._stable_correlation_id():
            raise ValidationError(
                _("The automation receipt correlation does not match.")
            )
        if receipt.get("state") not in MIDDLEWARE_EVENT_STATES:
            raise ValidationError(
                _("The automation receipt state is invalid.")
            )
        if receipt.get("projection") is not None:
            raise ValidationError(
                _("The Odoo automation receipt has an unexpected projection.")
            )

        duplicate = receipt.get("duplicate")
        if not isinstance(duplicate, bool):
            raise ValidationError(
                _("The automation receipt duplicate flag is invalid.")
            )
        receipt_event_id = receipt.get("event_id")
        accepted_event_ids = {
            self._transport_event_id(number)
            for number in range(1, attempt_number + 1)
        }
        if receipt_event_id not in accepted_event_ids:
            raise ValidationError(
                _("The automation receipt event identity is invalid.")
            )
        if status == 202 and (
            duplicate or receipt_event_id != transport_event_id
        ):
            raise ValidationError(
                _("The automation acceptance receipt is invalid.")
            )
        if status == 200 and not duplicate:
            raise ValidationError(
                _("The automation duplicate receipt is invalid.")
            )
        return {
            "status": status,
            "body_sha256": body_sha256,
            "receipt": "duplicate" if duplicate else "accepted",
        }

    def _post_event(self, config):
        """Post one authenticated attempt and reconcile exact replay receipts."""

        self.ensure_one()
        attempt_number = self.attempt_count + 1
        transport_event_id = self._transport_event_id(attempt_number)
        raw = json.dumps(
            self._envelope(config, transport_event_id),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        canonical = b"\n".join(
            (
                timestamp.encode("ascii"),
                transport_event_id.encode("utf-8"),
                MIDDLEWARE_SOURCE.encode("ascii"),
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
                "X-Event-Id": transport_event_id,
                "X-Event-Source": MIDDLEWARE_SOURCE,
                "X-Correlation-Id": self._stable_correlation_id(),
                "X-Tenant-Id": config["tenant_id"],
                "X-Timestamp": timestamp,
                "X-Signature": f"sha256={signature}",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        try:
            with opener.open(
                request,
                timeout=config["timeout"],
            ) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                return self._validated_receipt(
                    status=int(response.status),
                    body=body,
                    attempt_number=attempt_number,
                    transport_event_id=transport_event_id,
                )
        except urllib.error.HTTPError as exc:
            if int(exc.code) != 409:
                raise
            body = exc.read(MAX_RESPONSE_BYTES + 1)
            return self._validated_receipt(
                status=409,
                body=body,
                attempt_number=attempt_number,
                transport_event_id=transport_event_id,
            )
