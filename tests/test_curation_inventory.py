from scripts.curation_inventory import content_findings


def test_detects_synthetic_password_assignment():
    assert "credential assignment" in content_findings(
        b"password=synthetic-secret-value\n")


def test_detects_synthetic_client_secret_with_whitespace():
    assert "credential assignment" in content_findings(
        b"client_secret: synthetic-secret-value\n")


def test_detects_synthetic_bearer_authorization():
    assert "authorization header" in content_findings(
        b"Authorization: Bearer synthetic-token-value\n")


def test_does_not_cross_newline_for_assignment():
    findings = content_findings(b"password=\nsynthetic-public-value\n")
    assert "credential assignment" not in findings
