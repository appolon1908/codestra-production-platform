from pathlib import Path


SCRIPT = Path("operations/readiness/kong-caddy-middleware-audit.sh").read_text()


def test_audit_uses_verified_tls_by_default_and_file_based_auth():
    assert "--cacert" in SCRIPT
    assert "--cert" in SCRIPT and "--key" in SCRIPT
    assert "KONG_ADMIN_TOKEN_FILE" in SCRIPT
    assert "--insecure-local-tls" in SCRIPT
    assert "CURL_ARGS=(-k" not in SCRIPT


def test_audit_pagination_is_loop_safe_and_unlimited_by_default():
    assert "KONG_MAX_PAGES=${KONG_MAX_PAGES:-0}" in SCRIPT
    assert "declare -A visited=()" in SCRIPT
    assert "PAGINATION_LOOP_DETECTED" in SCRIPT
    assert "UNSAFE_PAGINATION_URL" in SCRIPT


def test_audit_discovers_kong_from_runtime_metadata():
    assert "docker ps -aq" in SCRIPT
    assert "^KONG_(DATABASE|ROLE|ADMIN_LISTEN|PROXY_LISTEN" in SCRIPT
    assert "com.docker.compose.service" in SCRIPT


def test_audit_redacts_sensitive_topology_and_logs_by_default():
    assert "show_topology=false" in SCRIPT
    assert "include_logs=false" in SCRIPT
    assert "umask 077" in SCRIPT
    assert 'chmod 600 "$output_file"' in SCRIPT
    assert 'if $show_topology; then\n    jq .' in SCRIPT


def test_audit_does_not_put_secret_values_in_output():
    assert "cat \"$KONG_ADMIN_TOKEN_FILE\"" not in SCRIPT
    assert "echo \"$token\"" not in SCRIPT
    assert "set -x" not in SCRIPT
