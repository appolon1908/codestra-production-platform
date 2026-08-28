import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_platform_authority_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_platform_authority.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Platform authority validation passed" in result.stdout


def test_platform_catalog_has_no_legacy_kyqra_repository() -> None:
    files = [
        ROOT / "contracts/catalog.v1.json",
        ROOT / "composition/runtime-composition.v1.json",
    ]
    for path in files:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert "appolon1908-hue/kyqra\"" not in json.dumps(value, sort_keys=True)


def test_caddy_has_one_documented_git_home() -> None:
    readme = (ROOT / "operations/caddy/README.md").read_text(encoding="utf-8")
    assert "canonical Git home" in readme
    assert "operations/caddy/" in (ROOT / "README.md").read_text(encoding="utf-8")
