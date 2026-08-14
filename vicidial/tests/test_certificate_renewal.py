from pathlib import Path


def test_renewal_units_are_fail_closed() -> None:
    root = Path(__file__).parents[1] / "ops" / "certificate-renewal"
    service = (root / "codestra-vicidial-certificate-renewal.service").read_text()
    timer = (root / "codestra-vicidial-certificate-renewal.timer").read_text()
    script = (root / "codestra_certificate_renewal.py").read_text()
    assert "OnCalendar=*-*-* 00,12:00:00" in timer
    assert "RandomizedDelaySec=30m" in timer
    assert "Persistent=true" in timer
    assert "os.replace(new_cert, cert)" in script
    assert "os.replace(backup_cert, cert)" in script
    assert "validate_leaf(new_cert, new_key, ca, identity)" in script
    assert "alert=certificate_renewal_failure" in script
    assert "(30, 14, 7, 3, 1)" in script
    assert "PrivateTmp=yes" in service
    assert "ProtectSystem=strict" in service


def test_production_identity_is_exact() -> None:
    text = (
        Path(__file__).parents[1]
        / "ops"
        / "certificate-renewal"
        / "observer-server.json.example"
    ).read_text()
    assert "DNS:vici-agent" in text
    assert "IP Address:10.40.0.2" in text
    assert "spiffe://codestra.internal/agent/vici" in text
    assert '"purpose": "sslserver"' in text
