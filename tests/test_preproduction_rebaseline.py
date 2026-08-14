import csv
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_requirement_ledger_uses_only_approved_states() -> None:
    allowed = {"IMPLEMENTED", "TESTED", "EVIDENCE_ATTACHED", "BLOCKED", "TARGET_PHASE_2"}
    with (ROOT / "reports/preproduction/REQUIREMENT_STATUS.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {row["status"] for row in rows} <= allowed
    assert all(row["evidence_or_blocker"] for row in rows)


def test_preproduction_flags_are_exactly_fail_closed() -> None:
    expected = {
        "SEND_EVENTS": "false",
        "ENABLE_EXTERNAL_DELIVERY": "false",
        "LIVE_WRITE": "false",
        "ODOO_WRITE": "false",
        "N8N_DELIVERY_ENABLED": "false",
        "PRODUCTION_DIALING": "DISABLED",
        "LIVE_CALL_CONTROL": "DISABLED",
        "GENERAL_AI_DIALING": "DISABLED",
    }
    values = {}
    for line in (ROOT / "config/preproduction-safety.env.example").read_text().splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    assert values == expected


def test_release_workflow_requires_signing_and_exact_protected_ref() -> None:
    workflow = (ROOT / ".github/workflows/protected-release.yml").read_text()
    assert "refs/heads/release/production-activation" in workflow
    assert "CODESTRA_RELEASE_SIGNING_KEY" in workflow
    assert "CODESTRA_RELEASE_SIGNING_PUBLIC_KEY" in workflow
    assert "ssh-keygen -Y verify" in workflow
    assert "gh release create" in workflow
