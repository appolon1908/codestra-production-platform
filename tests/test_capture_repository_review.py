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


def test_security_alert_api_errors_are_reported_as_blockers(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "OUT", tmp_path)
    monkeypatch.setattr(module, "KNOWN_REPOSITORIES", ("example/service",))

    def fake_gh(path, *, paginate=False):
        if path == "repos/example/service":
            return {
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
    inventory = json.loads((tmp_path / "REPOSITORY-INVENTORY.json").read_text())
    alerts = inventory["repositories"][0]["security_alerts"]
    assert alerts["dependabot"]["count"] == 0
    assert alerts["dependabot"]["error"].startswith("HTTP 403")
    assert "Canonical Middleware exact-head" in blockers
    assert "Kong runtime read-back" in blockers
