from pathlib import Path


SOURCE = Path("scripts/reconcile_test_syn_keycloak_subject.py").read_text()


def test_exact_identity_contract_is_pinned():
    assert 'USERNAME = "synthetic.agent.test.syn.6101"' in SOURCE
    assert 'CANONICAL_SUBJECT = "46c6027f-1ea8-4010-a104-5b908aabb715"' in SOURCE
    assert 'STALE_SUBJECT = "ca9b1218-c2d0-43f0-9c16-15cc60d7b0f4"' in SOURCE


def test_reconciliation_defaults_to_dry_run_and_refuses_credentials():
    assert 'parser.add_argument("--apply", action="store_true")' in SOURCE
    assert "refusing subject replacement because user has credentials" in SOURCE


def test_supported_partial_import_is_used_for_exact_uuid():
    assert 'partialImport' in SOURCE
    assert 'ifResourceExists": "FAIL"' in SOURCE
