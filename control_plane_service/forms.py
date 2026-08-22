from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .core import ControlPlaneError, Store
from .crm import CrmService, request_hash

ORIGINS = {"https://codestra.co", "https://www.codestra.co"}
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE = re.compile(r"^[+0-9(). -]{7,32}$")

COMMON_LEAD = {
    "full_name", "business_name", "work_email", "phone_number", "country",
    "preferred_language", "industry", "employee_count", "monthly_call_volume",
    "product_interest", "preferred_demo_date", "preferred_demo_time", "message",
    "consent", "sms_consent", "email_marketing_consent", "disclosure_version",
    "honeypot", "content_locale", "country_code", "locale_source",
    "translation_version", "solution", "attribution", "landing_page_url",
    "referrer", "cta_clicked", "anonymous_session_id",
}

BILLING_REGISTRATION_FIELDS = {
    "address_reference", "visiting_hours", "representation_rnc",
    "name_of_representative", "representative_phone",
    "representative_cell_phone", "representative_email",
    "operation_carried_out_in_premise", "street_of_warehouse",
    "store_or_warehouse_number", "province_of_warehouse",
    "warehouse_reference", "local_administration", "warehouse_sector",
    "tax_payer_rnc", "name_of_tax_payer", "trade_name",
    "tax_payer_telephone", "tax_payer_cell_phone", "tax_payer_email",
    "tax_payer_number", "tax_payer_sector", "tax_payer_province",
    "consent_to_contact", "sms_consent", "email_marketing_consent",
    "disclosure_version", "honeypot",
}

REGISTRY: dict[str, dict[str, Any]] = {
    "sales-contact": {
        "version": "1.0", "fields": {"full_name", "email", "company_size", "message", "honeypot"},
        "required": {"full_name", "email", "company_size", "message"},
        "source": "codestra.co", "campaign": "Website Sales Contact", "limit": 16384,
        "classification": "contact", "odoo_target": "crm.lead",
        "business_unit": "Website Forms Intake", "n8n_event": "crm.lead.created",
    },
    "demo-request": {
        "version": "1.0", "fields": COMMON_LEAD, "required": {"full_name", "work_email", "phone_number", "consent"},
        "source": "codestra.co", "campaign": "Website Demo Request", "limit": 32768,
        "classification": "lead", "odoo_target": "crm.lead",
        "business_unit": "Website Forms Intake", "n8n_event": "crm.lead.created",
    },
    "pricing-request": {
        "version": "1.0", "fields": COMMON_LEAD, "required": {"full_name", "work_email", "phone_number", "consent"},
        "source": "codestra.co", "campaign": "Website Pricing Request", "limit": 32768,
        "classification": "lead", "odoo_target": "crm.lead",
        "business_unit": "Website Forms Intake", "n8n_event": "crm.lead.created",
    },
    "electronic-billing-application": {
        "version": "1.0", "fields": {"full_name", "email", "phone", "uses_erp", "consent_to_contact", "honeypot"},
        "required": {"full_name", "email", "phone", "uses_erp", "consent_to_contact"},
        "source": "codestra.co", "campaign": "Electronic Billing Application", "limit": 16384,
        "classification": "lead", "odoo_target": "crm.lead",
        "business_unit": "Website Forms Intake", "n8n_event": "crm.lead.created",
    },
    "electronic-billing-registration": {
        "version": "1.0", "fields": BILLING_REGISTRATION_FIELDS,
        "required": BILLING_REGISTRATION_FIELDS - {
            "sms_consent", "email_marketing_consent", "disclosure_version", "honeypot"
        },
        "source": "codestra.co", "campaign": "Electronic Billing Registration", "limit": 32768,
        "classification": "registration", "odoo_target": "crm.lead",
        "business_unit": "Website Forms Intake", "n8n_event": "crm.lead.created",
    },
}


def _text(value: Any, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ControlPlaneError("invalid_field")
    return value.strip()


def _optional_text(value: Any, maximum: int = 500) -> str:
    if value in (None, ""):
        return ""
    return _text(value, maximum)


def _validate_payload(form: str, payload: dict[str, Any]) -> None:
    boolean_fields = {"consent", "sms_consent", "email_marketing_consent", "uses_erp", "consent_to_contact"}
    for field in boolean_fields & payload.keys():
        if not isinstance(payload[field], bool):
            raise ControlPlaneError("invalid_field:" + field)
    if "attribution" in payload:
        attribution = payload["attribution"]
        if not isinstance(attribution, dict) or len(attribution) > 24:
            raise ControlPlaneError("invalid_field:attribution")
        for key, value in attribution.items():
            if not isinstance(key, str) or len(key) > 64 or not isinstance(value, (str, int, float, bool, type(None), dict)):
                raise ControlPlaneError("invalid_field:attribution")
    short_fields = {
        "full_name", "business_name", "company_size", "country", "preferred_language",
        "industry", "product_interest", "preferred_demo_date", "preferred_demo_time",
        "disclosure_version", "content_locale", "country_code", "locale_source", "solution",
        "cta_clicked", "anonymous_session_id", "uses_erp",
    }
    url_fields = {"landing_page_url", "referrer"}
    long_fields = {"message"}
    for field in (set(payload) - boolean_fields - {"attribution", "honeypot"}):
        if field in {"email", "work_email", "phone", "phone_number"}:
            continue
        maximum = 4000 if field in long_fields else 2048 if field in url_fields else 500
        try:
            _optional_text(payload[field], maximum)
        except ControlPlaneError as exc:
            raise ControlPlaneError("invalid_field:" + field) from exc
    if form == "electronic-billing-registration":
        for field in REGISTRY[form]["required"] - {"consent_to_contact"}:
            _text(payload[field], 500)


class FormService:
    def __init__(self, store: Store): self.store = store

    def submit(self, form: str, payload: dict[str, Any], headers: Any, raw_size: int) -> tuple[int, dict[str, Any]]:
        spec = REGISTRY.get(form)
        if not spec: raise ControlPlaneError("form_not_found")
        origin = headers.get("Origin", "")
        if origin not in ORIGINS: raise ControlPlaneError("origin_denied")
        if raw_size > spec["limit"]: raise ControlPlaneError("body_too_large")
        unsupported = sorted(set(payload) - spec["fields"])
        if unsupported: raise ControlPlaneError("unsupported_fields:" + ",".join(unsupported))
        if spec["required"] - set(payload): raise ControlPlaneError("missing_required_fields")
        if payload.get("honeypot"): raise ControlPlaneError("bot_rejected")
        _validate_payload(form, payload)
        key = headers.get("Idempotency-Key", "").strip()
        if not key or len(key) > 200: raise ControlPlaneError("idempotency_key_required")
        correlation = headers.get("X-Correlation-ID", "").strip() or str(uuid.uuid4())
        email = _text(payload.get("work_email", payload.get("email", payload.get("tax_payer_email", ""))), 254).lower()
        if not EMAIL.match(email): raise ControlPlaneError("invalid_email")
        phone = str(payload.get("phone_number", payload.get("phone", payload.get("tax_payer_telephone", "")))).strip()
        if phone and not PHONE.match(phone): raise ControlPlaneError("invalid_phone")
        if form in {"demo-request", "pricing-request"} and payload.get("consent") is not True:
            raise ControlPlaneError("contact_consent_required")
        if form == "electronic-billing-application" and payload.get("consent_to_contact") is not True:
            raise ControlPlaneError("contact_consent_required")
        if form == "electronic-billing-registration" and payload.get("consent_to_contact") is not True:
            raise ControlPlaneError("contact_consent_required")

        name = _text(payload.get("full_name", payload.get("name_of_tax_payer", "")), 160)
        fingerprint = hashlib.sha256((form + "|" + email + "|" + re.sub(r"\D", "", phone)).encode()).hexdigest()[:24]
        disclosure = str(payload.get("disclosure_version") or spec["version"])
        consent = {
            "contact": bool(payload.get("consent") or payload.get("consent_to_contact")),
            "sms": bool(payload.get("sms_consent", False)),
            "email_marketing": bool(payload.get("email_marketing_consent", False)),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "disclosure_version": disclosure,
            "source_site": spec["source"], "phone": phone or None, "correlation_id": correlation,
        }
        safe_detail = {k: v for k, v in payload.items() if k not in {"honeypot", "consent", "sms_consent", "email_marketing_consent"}}
        description = json.dumps({"form": form, "form_version": spec["version"], "fields": safe_detail, "consent_evidence": consent}, sort_keys=True)
        outbound = {
            "name": f"Website {form}: {name}", "contact_name": name, "email": email,
            "phone": phone, "company_name": str(payload.get("business_name", ""))[:160],
            "source": spec["source"], "campaign": spec["campaign"], "description": description,
            # A UTC-day bucket gives bounded duplicate suppression independent
            # of browser retry keys while preserving a fresh intake next day.
            "customer_reference": f"form-{form}-{fingerprint}-{datetime.now(timezone.utc):%Y%m%d}",
        }
        customer = self.store.crm_customer_by_id(os.getenv("FORM_CRM_CUSTOMER_ID", "crm-synthetic-customer"))
        operation = "form." + form + ".create"; digest = request_hash(payload)
        prior = self.store.crm_idempotency(customer["customer_id"], operation, key, digest)
        if prior:
            result, status = prior; result.update({"duplicate": True, "correlation_id": correlation}); return status, result
        try:
            self.store.crm_object(customer["customer_id"], outbound["customer_reference"])
            result = {"request_id": outbound["customer_reference"], "status": "accepted", "duplicate": True,
                      "correlation_id": correlation, "form": form, "form_version": spec["version"]}
            self.store.crm_save_idempotency(customer["customer_id"], operation, key, digest, result, 200)
            return 200, result
        except ControlPlaneError as exc:
            if str(exc) != "crm_object_not_found": raise
        crm = CrmService(self.store)
        outbound_odoo = {**outbound, "external_id": outbound["customer_reference"], "middleware_id": str(uuid.uuid4())}
        outbound_odoo.update({
            "form_type": form, "form_version": spec["version"], "source_site": spec["source"],
            "consent_timestamp": consent["timestamp"], "consent_disclosure_version": disclosure,
            "sms_consent": consent["sms"], "email_marketing_consent": consent["email_marketing"],
            "consent_correlation_id": correlation,
        })
        status, result = crm.call(customer, "POST", "/leads", outbound_odoo, correlation, "form:" + form + ":" + key)
        if status >= 300: return status, {**result, "correlation_id": correlation}
        self.store.crm_save_object(customer["customer_id"], outbound["customer_reference"], outbound_odoo["middleware_id"], "crm.lead")
        result = {"request_id": result["external_id"], "status": "accepted", "duplicate": False,
                  "correlation_id": correlation, "form": form, "form_version": spec["version"]}
        self.store.crm_save_idempotency(customer["customer_id"], operation, key, digest, result, status)
        self.store.crm_audit(customer["customer_id"], operation, outbound["customer_reference"], list(payload), "success", status, correlation)
        # Reuse the governed authenticated n8n CRM-created workflow. Form type
        # and version are durable Odoo fields, not a browser-selected event.
        crm.emit(customer, "crm.lead.created", outbound["customer_reference"], correlation)
        return status, result
