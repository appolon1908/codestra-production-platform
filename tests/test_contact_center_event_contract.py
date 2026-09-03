import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


SCHEMA = json.loads(
    Path("schemas/contact-center-event-envelope-v1.schema.json").read_text()
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def event(**changes):
    document = {
        "event_id": "evt_fixture_1",
        "event_type": "call.ended",
        "schema_version": 1,
        "occurred_at": "2026-08-23T12:00:00Z",
        "source": "vicidial",
        "tenant_id": "company-fixture",
        "campaign_id": "campaign-fixture",
        "correlation_id": "8d7a0f0b-b49b-49a7-b555-89aa62e49c90",
        "subject": {"type": "call_leg", "id": "vicidial-call-fixture"},
        "data": {},
    }
    document.update(changes)
    return document


def test_contact_center_event_envelope_accepts_canonical_event():
    assert not list(VALIDATOR.iter_errors(event()))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("event_type", "provider.arbitrary_action"),
        ("correlation_id", "not-a-uuid"),
    ],
)
def test_contact_center_event_envelope_rejects_unsupported_contract(field, value):
    assert list(VALIDATOR.iter_errors(event(**{field: value})))


def test_contact_center_event_envelope_rejects_unknown_fields():
    assert list(VALIDATOR.iter_errors(event(executable_workflow_id="untrusted")))
