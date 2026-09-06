from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_required_repository_authority_deliverables_exist():
    for name in (
        "REPOSITORY-AUTHORITY-MATRIX.yaml",
        "REPOSITORY-LIFECYCLE.md",
        "DEPRECATED-REPOSITORIES.md",
        "SERVICE-OWNER-MATRIX.yaml",
    ):
        assert (ROOT / name).is_file()


def test_unapproved_owner_assignments_fail_closed():
    document = yaml.safe_load((ROOT / "SERVICE-OWNER-MATRIX.yaml").read_text())
    assert document["status"] == "FAIL"
    assert len(document["services"]) == 14
    for service in document["services"]:
        assert set(("source_authority", "database_authority", "runtime_authority", "security_owner", "business_owner")) <= service.keys()
    assert any("PENDING" in str(value) for service in document["services"] for value in service.values())


def test_no_repository_is_falsely_deprecated():
    lifecycle = (ROOT / "DEPRECATED-REPOSITORIES.md").read_text()
    assert "NONE APPROVED" in lifecycle
    assert "must not be archived, deleted" in lifecycle
