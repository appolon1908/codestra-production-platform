from pathlib import Path

import pytest
import yaml

from tools.validate_fail_closed_override import REQUIRED_FLAGS, validate


ROOT = Path(__file__).parents[1]
OVERRIDE = ROOT / "operations/production-operator/compose.production-fail-closed.yaml"


def test_canonical_override_is_complete_and_false() -> None:
    validate(OVERRIDE)
    environment = yaml.safe_load(OVERRIDE.read_text())["services"]["middleware"]["environment"]
    assert set(environment) == REQUIRED_FLAGS
    assert set(environment.values()) == {"false"}


@pytest.mark.parametrize("failure", ["missing", "enabled", "extra-service"])
def test_invalid_override_fails_closed(tmp_path: Path, failure: str) -> None:
    document = yaml.safe_load(OVERRIDE.read_text())
    environment = document["services"]["middleware"]["environment"]
    if failure == "missing":
        environment.pop("GENERAL_AI_DIALING")
    elif failure == "enabled":
        environment["LIVE_WRITE"] = "true"
    else:
        document["services"]["postgres"] = {}
    candidate = tmp_path / "override.yaml"
    candidate.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError):
        validate(candidate)
