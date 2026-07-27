import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).parents[1] / "scripts" / "synthetic_automatic_campaign_gate.py"
SPEC = importlib.util.spec_from_file_location("campaign_gate", PATH)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(gate)


def safe():
    return {
        "ENVIRONMENT": "staging",
        "BUSINESS_UNIT": "MOY",
        "CANONICAL_CAMPAIGN": "MOY-TEST-OUT",
        "VICIDIAL_CAMPAIGN": "MOYDCB3B",
        "VICIDIAL_LIST_ID": "91001",
        "TEST_AGENT": "synthetic-campaign-agent",
        "TEST_ENDPOINT": "6101",
        "ADAPTER_URL": "https://edge.internal.codestra.agency:8443",
        **{flag: "false" for flag in gate.FALSE_FLAGS},
    }


def private(_host):
    return ("edge.internal.codestra.agency", [], ["10.40.0.2"])


def test_safe_contract_and_manifest():
    values = safe()
    gate.validate(values, resolver=private)
    output = gate.redacted_manifest(values)
    assert output["manifest"]["vicidial"]["active"] is False
    assert output["manifest"]["lead"]["telephone_number"] is None
    assert output["manifest"]["n8n"]["active"] is False
    assert output["manifest"]["transfer_policy"] == "same-campaign-only"
    assert len(output["sha256"]) == 64


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ENVIRONMENT", "production"),
        ("VICIDIAL_LIST_ID", "90001"),
        ("TEST_ENDPOINT", "6102"),
        ("PRODUCTION_DIALING", "true"),
        ("EXTERNAL_COMMUNICATION", "true"),
    ],
)
def test_unsafe_inputs_fail_closed(key, value):
    values = safe()
    values[key] = value
    with pytest.raises(RuntimeError):
        gate.validate(values, resolver=private)


def test_public_resolution_fails_closed():
    with pytest.raises(RuntimeError):
        gate.validate(
            safe(),
            resolver=lambda _host: (
                "edge.internal.codestra.agency",
                [],
                ["65.21.67.207"],
            ),
        )
