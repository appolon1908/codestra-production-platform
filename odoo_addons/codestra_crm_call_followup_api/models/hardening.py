from __future__ import annotations

import json

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import email_split

from .call_followup_api import API_VERSION


MAX_PAYLOAD_BYTES = 65_536
MAX_CUSTOMER_EMAIL_LENGTH = 320


class CodestraCrmCallFollowupApiHardening(models.Model):
    """Fail-closed limits layered onto the versioned completed-call API."""

    _inherit = "codestra.crm.call.followup"

    @api.model
    def _api_normalize_payload(self, payload, strict=False):
        if isinstance(payload, dict):
            try:
                raw_payload = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    _("The completed-call payload contains unsupported values.")
                ) from exc
            if len(raw_payload) > MAX_PAYLOAD_BYTES:
                raise ValidationError(
                    _("The completed-call payload cannot exceed 65,536 bytes.")
                )

            supplied_version = payload.get("api_version")
            if (
                strict
                and supplied_version is not None
                and str(supplied_version).strip()
                and str(supplied_version).strip() != API_VERSION
            ):
                raise ValidationError(
                    _("Unsupported completed-call API version.")
                )

        normalized = super()._api_normalize_payload(
            payload,
            strict=strict,
        )

        customer_email = normalized.get("customer_email")
        if customer_email:
            customer_email = str(customer_email).strip()
            if len(customer_email) > MAX_CUSTOMER_EMAIL_LENGTH:
                raise ValidationError(
                    _("customer_email cannot exceed 320 characters.")
                )
            parsed = email_split(customer_email)
            if (
                len(parsed) != 1
                or parsed[0].casefold() != customer_email.casefold()
            ):
                raise ValidationError(
                    _("customer_email must contain one valid email address.")
                )
            normalized["customer_email"] = parsed[0].lower()

        return normalized

    @api.model
    def get_integration_capabilities(self):
        capabilities = super().get_integration_capabilities()
        capabilities["supported_api_versions"] = [API_VERSION]
        capabilities["limits"].update(
            {
                "max_payload_bytes": MAX_PAYLOAD_BYTES,
                "max_customer_email_length": MAX_CUSTOMER_EMAIL_LENGTH,
            }
        )
        return capabilities
