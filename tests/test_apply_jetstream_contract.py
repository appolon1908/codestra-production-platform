from __future__ import annotations

import asyncio
from pathlib import Path
import ssl
from types import SimpleNamespace

import pytest
import yaml

from tools import apply_jetstream_contract as applicator


def stream_contract():
    return {
        "streams": [
            {
                "name": "TEST_STREAM",
                "subjects": ["codestra.v1.*.*.events.test"],
                "retention": "limits",
                "replicas": 1,
                "max_age_seconds": 60,
                "duplicate_window_seconds": 120,
                "max_message_bytes": 1024,
                "deny_delete": True,
                "deny_purge": True,
            }
        ],
        "consumers": [],
    }


def test_stream_mutation_requires_matching_readback(monkeypatch) -> None:
    class Manager:
        def __init__(self):
            self.config = None

        async def stream_info(self, name):
            assert name == "TEST_STREAM"
            if self.config is None:
                return SimpleNamespace(config=SimpleNamespace())
            actual = SimpleNamespace(
                **{
                    field: getattr(self.config, field)
                    for field in (
                        "subjects",
                        "retention",
                        "storage",
                        "num_replicas",
                        "max_age",
                        "duplicate_window",
                        "max_msg_size",
                        "deny_delete",
                        "deny_purge",
                    )
                }
            )
            actual.max_msg_size += 1
            return SimpleNamespace(config=actual)

        async def update_stream(self, config):
            self.config = config

    manager = Manager()

    class Client:
        def jetstream(self):
            return manager

        async def drain(self):
            return None

    async def connect(*args, **kwargs):
        return Client()

    monkeypatch.setattr(applicator, "load_contract", lambda path=None: stream_contract())
    monkeypatch.setattr(applicator.nats, "connect", connect)
    with pytest.raises(RuntimeError, match="stream TEST_STREAM differs"):
        asyncio.run(applicator.apply_contract("nats://isolated"))


def test_tls_context_requires_ca_and_client_identity(monkeypatch) -> None:
    calls = []

    class Context:
        minimum_version = None

        def load_cert_chain(self, cert, key):
            calls.append((cert, key))

    context = Context()
    monkeypatch.setattr(
        applicator.ssl,
        "create_default_context",
        lambda *, cafile: calls.append(cafile) or context,
    )
    result = applicator.tls_context(
        Path("ca.pem"), Path("client.pem"), Path("client-key.pem")
    )
    assert result is context
    assert calls == [Path("ca.pem"), (Path("client.pem"), Path("client-key.pem"))]
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2


def test_source_gate_covers_release_deployment_and_docs() -> None:
    workflow = Path(".github/workflows/platform-source-gate.yml").read_text()
    definition = yaml.load(workflow, Loader=yaml.BaseLoader)
    assert "pull_request" in definition["on"]
    assert definition["on"]["pull_request"] in (None, "", {})
    validate = definition["jobs"]["validate"]
    assert "if" not in validate
    suite = next(step for step in validate["steps"]
                 if step.get("name") == "Run complete clean-checkout platform suite")
    assert "if" not in suite and "continue-on-error" not in suite
    assert "-m pytest -q" in suite["run"]
