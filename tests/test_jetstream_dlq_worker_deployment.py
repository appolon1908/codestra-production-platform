from pathlib import Path


def test_dlq_worker_is_deployable_and_fail_closed() -> None:
    unit = Path("deploy/codestra-jetstream-dlq-worker.service").read_text()
    environment = Path("config/jetstream-dlq-worker.env.example").read_text()
    assert "${MIDDLEWARE_IMAGE} python -m app.entrypoints.jetstream_dlq_worker" in unit
    assert "tools/run_jetstream_dlq_worker.py" not in unit
    assert "ghcr.io/codestra-srl/codestra-middleware@sha256:REQUIRED" in environment
    assert "--read-only" in unit
    assert "--cap-drop ALL" in unit
    assert "--mount type=bind,src=/run/codestra/nats" in unit
    assert "tools/verify_jetstream_worker_image.py" in unit
    assert "--manifest /etc/codestra/deployment-manifest.json" in unit
    assert "JETSTREAM_DLQ_WORKER_ENABLED=false" in environment
