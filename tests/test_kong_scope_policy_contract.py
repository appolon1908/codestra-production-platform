import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def scopes(value: str) -> set[str]:
    return set(re.findall(r'required\s*=\s*"([a-z0-9_.-]+)"', value))


def test_standalone_and_embedded_kong_scope_policies_cannot_drift():
    standalone = (ROOT / "deploy/kong/scope-policy.lua").read_text()
    declarative = (ROOT / "deploy/kong/control-plane.yml").read_text()
    embedded = declarative.split("- |", 1)[1].split("  - name: codestra-agent-realtime-sessions", 1)[0]
    assert scopes(standalone) == scopes(embedded)
    for required in ("automation.execute", "automation.result.write", "platform.admin"):
        assert required in scopes(standalone)
