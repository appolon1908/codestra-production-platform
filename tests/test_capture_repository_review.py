import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "capture_repository_review.py"


def load_module():
    spec = importlib.util.spec_from_file_location("capture_repository_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def fake_exporter(repository="example/service", repository_id=123456):
    return {
        "repository_id": repository_id,
        "repository": repository,
        "public_hostname": None,
        "private_service_identity": "postgres-exporter:9187",
        "forbidden_public_hostname": "pgex.codestra.media",
        "exposure": "PRIVATE_INTERNAL_ONLY",
    }


def test_security_alert_api_errors_are_reported_as_blockers(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "OUT", tmp_path)
    monkeypatch.setattr(module, "KNOWN_REPOSITORIES", ("example/service",))
    monkeypatch.setattr(module, "load_repository_aliases", lambda: {})
    monkeypatch.setattr(
        module,
        "load_postgres_exporter_authority",
        lambda: fake_exporter(),
    )

    def fake_gh(path, *, paginate=False):
        if path == "repos/example/service":
            return {
                "id": 123456,
                "full_name": "example/service",
                "default_branch": "main",
                "visibility": "private",
                "archived": False,
            }, None
        if "/dependabot/alerts" in path:
            return None, "HTTP 403: Resource not accessible by integration"
        if "/secret-scanning/alerts" in path:
            return [], None
        if "/code-scanning/alerts" in path:
            return None, "HTTP 404: Advanced Security must be enabled"
        if "/actions/workflows" in path:
            return {"workflows": []}, None
        if "/actions/runs" in path:
            return {"workflow_runs": []}, None
        return [], None

    monkeypatch.setattr(module, "gh", fake_gh)
    module.main()

    blockers = (tmp_path / "REPOSITORY-BLOCKERS.md").read_text()
    assert "dependabot security alerts: HTTP 403" in blockers
    assert "code_scanning security alerts: HTTP 404" in blockers
    assert "Canonical Middleware exact-head" in blockers
    assert "Server 65 Kong runtime read-back" in blockers
    inventory = json.loads((tmp_path / "REPOSITORY-INVENTORY.json").read_text())
    record = inventory["repositories"][0]
    assert record["repository_id"] == 123456
    assert record["expected_repository_id"] == 123456
    alerts = record["security_alerts"]
    assert alerts["dependabot"]["count"] == 0
    assert alerts["dependabot"]["error"].startswith("HTTP 403")


def test_blocked_metadata_keeps_observed_id_null_and_expected_id_separate():
    module = load_module()
    record = module.metadata_blocked_record(
        "appolon1908-hue/Frontend-Resturant-",
        "HTTP 403",
        {
            "repository_id": 1221155447,
            "target_repository_after_cutover": "appolon1908-hue/restaurant-frontend",
            "status": "PREPARED_NOT_RENAMED",
        },
        1221155447,
    )

    assert record["status"] == "BLOCKED"
    assert record["repository_id"] is None
    assert record["expected_repository_id"] == 1221155447
    assert record["target_repository_after_cutover"] == (
        "appolon1908-hue/restaurant-frontend"
    )


def test_postgres_exporter_id_mismatch_is_blocked(monkeypatch):
    module = load_module()
    blockers = []
    rows = []
    repository = "appolon1908-hue/Codestra-Postgres-Exporter"

    def fake_gh(path, *, paginate=False):
        assert path == f"repos/{repository}"
        return {"id": 999, "full_name": repository, "default_branch": "main"}, None

    monkeypatch.setattr(module, "gh", fake_gh)
    record = module.capture_repository(
        repository,
        None,
        1350839865,
        blockers,
        rows,
    )

    assert record["status"] == "BLOCKED"
    assert record["repository_id"] == 999
    assert record["expected_repository_id"] == 1350839865
    assert "stable repository ID mismatch" in record["error"]
    assert blockers and "expected 1350839865" in blockers[0]
    assert rows == []


def test_premature_repository_redirect_is_blocked(monkeypatch):
    module = load_module()
    blockers = []
    rows = []
    current = "appolon1908-hue/Frontend-Resturant-"
    target = "appolon1908-hue/restaurant-frontend"

    def fake_gh(path, *, paginate=False):
        assert path == f"repos/{current}"
        return {
            "id": 1221155447,
            "full_name": target,
            "default_branch": "main",
        }, None

    monkeypatch.setattr(module, "gh", fake_gh)
    record = module.capture_repository(
        current,
        {
            "repository_id": 1221155447,
            "target_repository_after_cutover": target,
            "status": "PREPARED_NOT_RENAMED",
        },
        1221155447,
        blockers,
        rows,
    )

    assert record["status"] == "BLOCKED"
    assert record["repository_id"] == 1221155447
    assert record["observed_full_name"] == target
    assert "canonical repository name mismatch" in record["error"]
    assert blockers and target in blockers[0]
    assert rows == []


def test_operational_blockers_survive_a_clean_api_capture(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "OUT", tmp_path)

    module.write_outputs("2026-09-02T00:00:00+00:00", [], [], [])

    blockers = (tmp_path / "REPOSITORY-BLOCKERS.md").read_text()
    assert "None observed during API capture" not in blockers
    assert "CANONICAL-MIDDLEWARE-ACTIONS-BLOCKER-20260902.md" in blockers
    assert "KONG-RUNTIME-READBACK-BLOCKER-20260902.md" in blockers


def test_alias_loading_is_decoupled_from_injected_capture_inventory(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "KNOWN_REPOSITORIES", ("example/service",))

    aliases = module.load_repository_aliases()

    assert len(aliases) == 6
    assert "appolon1908-hue/Frontend-Resturant-" in aliases
