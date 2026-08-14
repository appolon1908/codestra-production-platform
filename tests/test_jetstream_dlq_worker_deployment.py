from pathlib import Path


def test_dlq_worker_is_deployable_and_fail_closed() -> None:
    unit = Path("deploy/codestra-jetstream-dlq-worker.service").read_text()
    environment = Path("config/jetstream-dlq-worker.env.example").read_text()
    worker = Path("tools/run_jetstream_dlq_worker.py").read_text()
    assert "tools/run_jetstream_dlq_worker.py" in unit
    assert "JETSTREAM_DLQ_WORKER_ENABLED=false" in environment
    assert "production NATS transport must use TLS" in worker
    assert "subscribe_dead_letter_forwarder" in worker
