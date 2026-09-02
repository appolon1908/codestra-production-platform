from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools.validate_production_database_manifest import validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PRODUCTION-DATABASE-MANIFEST.yaml"


def test_production_database_manifest_is_complete_and_fail_closed():
    validate(MANIFEST)
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert document["certification_status"] == "FAIL"
    assert any(c["isolated_restore"] != "PASS" for c in document["components"])


def test_pass_cannot_be_claimed_without_every_restore_and_off_host_copy(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["certification_status"] = "PASS"
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(AssertionError):
        validate(candidate)


def test_missing_store_is_rejected(tmp_path):
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    document["components"] = deepcopy(document["components"][:-1])
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(AssertionError, match="coverage mismatch"):
        validate(candidate)
