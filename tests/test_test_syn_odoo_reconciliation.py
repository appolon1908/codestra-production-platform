from pathlib import Path


SOURCE = Path("scripts/reconcile_test_syn_odoo.py").read_text()


def test_exact_crosswalk_is_pinned():
    for value in ("46c6027f-1ea8-4010-a104-5b908aabb715", "synthetic.agent.test.syn.6101", "TEST_SYN", "6101", "cod00016"):
        assert value in SOURCE


def test_default_is_rollback_and_never_writes_vicidial():
    assert 'os.environ.get("TEST_SYN_APPLY") == "YES"' in SOURCE
    assert "env.cr.rollback()" in SOURCE
    assert "No VICIdial write is performed" in SOURCE


def test_synthetic_anchors_are_resolved_by_authoritative_keys():
    assert 'search([("code", "=", "COD")], limit=1)' in SOURCE
    assert '("login", "=", "synthetic.agent.test.syn.6101")' in SOURCE
    assert '("codestra_employee_number", "=", "COD.2026.00016")' in SOURCE
    assert ".browse(16)" not in SOURCE
    assert ".browse(129)" not in SOURCE
