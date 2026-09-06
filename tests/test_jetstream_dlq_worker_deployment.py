from pathlib import Path


def test_dlq_worker_is_deployable_and_fail_closed() -> None:
    unit = Path("deploy/codestra-jetstream-dlq-worker.service").read_text()
    environment = Path("config/jetstream-dlq-worker.env.example").read_text()
    assert "${MIDDLEWARE_IMAGE} python -m app.entrypoints.jetstream_dlq_worker" in unit
    assert "tools/run_jetstream_dlq_worker.py" not in unit
    assert "ghcr.io/appolon1908-hue/codestra-middleware@sha256:REQUIRED" in environment
    assert "--read-only" in unit
    assert "--cap-drop ALL" in unit
    assert "--mount type=bind,src=/run/codestra/nats" in unit
    assert "tools/verify_jetstream_worker_image.py" in unit
    assert "--manifest /etc/codestra/release/deployment-manifest.json" in unit
    assert "--checksums /etc/codestra/release/manifest.sha256" in unit
    assert "--signature /etc/codestra/release/manifest.sha256.sig" in unit
    assert "--allowed-signers /etc/codestra/release/allowed_signers" in unit
    trust = Path("tools/provision_release_trust_anchor.py").read_text()
    authority = Path("docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md").read_text()
    assert "expected-sha256" in trust
    assert "different release trust anchor is already installed" in trust
    assert "Out-of-band release trust anchor" in authority
    assert "/etc/codestra/release/allowed_signers" in authority
    assert "JETSTREAM_DLQ_WORKER_ENABLED=false" in environment
