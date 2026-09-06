from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("blocked_canary", ROOT / "operations/canary/create-blocked-evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def package(tmp_path):
    path = tmp_path / "evidence"
    MODULE.write_package(path, stamp="2026-09-04T22:00:00+00:00", head="a" * 40, host="test-only")
    return path


def test_missing_runtime_evidence_never_emits_pass_or_zero_global_calls(tmp_path):
    path = package(tmp_path)
    gates = (path / "GATES.env").read_text()
    assert "=PASS" not in gates
    assert "CALL_ATTEMPTS=0\n" not in gates
    assert "CALL_ATTEMPTS=UNKNOWN\n" in gates
    assert "CALL_ATTEMPTS_THIS_TOOL=0\n" in gates
    for key in ("CANARY_ROLLBACK_GATE", "CANARY_CLEANUP_GATE", "POST_CANARY_DISABLE_GATE", "CANARY_RECONCILIATION_GATE"):
        assert f"{key}=NOT_RUN\n" in gates
    assert "BUSINESS_FLOW_CERTIFICATION=BLOCKED\n" in gates
    assert "ACTIVATION_AUTHORIZED=false\n" in gates
    for text in MODULE.FILES.values():
        assert "GATE=PASS" not in text
        assert "1110_UNCHANGED" not in text
        assert "MONITORING_RUNTIME=ABSENT" not in text
        assert "FALSE_WHERE_OBSERVED" not in text


def test_integrity_success_explicitly_is_not_business_certification(tmp_path):
    path = package(tmp_path)
    result = subprocess.run(["bash", str(path / "verify-evidence.sh")], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "blocked_evidence_package_integrity=VERIFIED" in result.stdout
    assert "business_flow_certified=false" in result.stdout
    assert "signed_canary_blocked_evidence=VERIFIED" not in result.stdout


def test_tampering_fails_integrity_check(tmp_path):
    path = package(tmp_path)
    (path / "RECONCILIATION.tsv").write_text("VICIdial\tPASS\tfabricated\n")
    result = subprocess.run(["bash", str(path / "verify-evidence.sh")], capture_output=True, check=False)
    assert result.returncode != 0


def test_rehashing_a_fabricated_gate_does_not_make_blocked_package_valid(tmp_path):
    path = package(tmp_path)
    gates = path / "GATES.env"
    gates.write_text(gates.read_text().replace("CANARY_ROLLBACK_GATE=NOT_RUN", "CANARY_ROLLBACK_GATE=PASS"))
    sums = path / "SHA256SUMS"
    lines = []
    for line in sums.read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name == "GATES.env":
            digest = hashlib.sha256(gates.read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}")
    sums.write_text("\n".join(lines) + "\n")
    result = subprocess.run(["bash", str(path / "verify-evidence.sh")], capture_output=True, check=False)
    assert result.returncode != 0


def test_existing_evidence_cannot_be_overwritten(tmp_path):
    path = package(tmp_path)
    previous = (path / "GATES.env").read_bytes()
    with pytest.raises(FileExistsError):
        MODULE.write_package(path, stamp="later", head="b" * 40, host="different")
    assert (path / "GATES.env").read_bytes() == previous


def test_all_reconciliation_components_remain_unobserved(tmp_path):
    path = package(tmp_path)
    for line in (path / "RECONCILIATION.tsv").read_text().splitlines()[1:]:
        assert line.split("\t")[1] == "NOT_RUN"
