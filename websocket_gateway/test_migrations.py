from pathlib import Path

import yaml


def test_migration_chain_has_matching_head_and_rollback() -> None:
    root = Path(__file__).with_name("migrations")
    assert (root / "0001_realtime_gateway.up.sql").is_file()
    assert (root / "0001_realtime_gateway.down.sql").is_file()
    source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    assert 'DATABASE_MIGRATION_HEAD = "0001_realtime_gateway"' in source
    assert "CREATE TABLE IF NOT EXISTS realtime_sessions" not in source


def test_gateway_is_published_only_on_canonical_loopback_port() -> None:
    compose = yaml.safe_load(Path(__file__).with_name("compose.yaml").read_text())
    assert compose["services"]["gateway"]["ports"] == ["127.0.0.1:18102:8080"]


def test_open_socket_rechecks_persisted_session_expiry() -> None:
    source = Path(__file__).with_name("app.py").read_text()
    assert "remaining = (scope[\"expires_at\"] - now()).total_seconds()" in source
    assert "await session_is_active(websocket.app.state.pool, scope)" in source
    assert "session_expired_or_revoked" in source


def test_release_publication_serializes_by_version() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/websocket-6101-release.yml").read_text()
    assert "inputs.release_version || github.ref" in workflow


def test_certifier_uses_issued_token_subject() -> None:
    source = Path(__file__).with_name("certify.py").read_text()
    assert 'access_token.split(".")[1]' in source
    assert "user=token_subject" in source
    assert "2a725359-2b9d-42da-af45-9af008a61353" not in source


def test_recovery_pass_requires_exact_single_render_per_event() -> None:
    source = Path(__file__).with_name("recovery_certify.mjs").read_text()
    assertion = source.index("await deliveries.count() !== 1")
    result = source.index('REPLAY_EXACTLY_ONCE:"PASS"')
    assert assertion < result
