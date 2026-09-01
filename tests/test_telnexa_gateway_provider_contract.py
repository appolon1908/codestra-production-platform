from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest

from control_plane_service import providers


class Response:
    status = 202

    def __init__(self, value: dict[str, object]):
        self.raw = json.dumps(value, separators=(",", ":")).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        assert limit == 2049
        return self.raw


def production_message() -> dict[str, object]:
    return {
        "provider": "telnexa",
        "message_id": "ba6c50fa-2e38-41cb-b85b-8b153cb67ecf",
        "tenant_id": "tenant-a",
        "customer_id": "customer-1",
        "normalized_destination": "+4915512345678",
        "sender": "CODESTRA",
        "content_payload": json.dumps({"content": "bounded test"}),
        "correlation_id": "correlation-1",
        "idempotency_key": "idem-0001",
    }


def configure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> tuple[bytes, bytes]:
    api_key = b"control-plane-to-telnexa-api-key"
    hmac_secret = b"control-plane-to-telnexa-hmac-secret"
    api_key_path = tmp_path / "telnexa-api-key"
    hmac_path = tmp_path / "telnexa-hmac-secret"
    api_key_path.write_bytes(api_key + b"\n")
    hmac_path.write_bytes(hmac_secret + b"\n")
    monkeypatch.setenv("TELNEXA_MODE", "production")
    monkeypatch.setenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED", "true")
    monkeypatch.setenv(
        "TELNEXA_URL", "https://telnexa.internal.codestra.agency:8443/v1/messages"
    )
    monkeypatch.setenv("TELNEXA_OUTBOUND_API_KEY_FILE", str(api_key_path))
    monkeypatch.setenv("TELNEXA_OUTBOUND_HMAC_SECRET_FILE", str(hmac_path))
    monkeypatch.setattr(providers.time, "time", lambda: 2_000_000_000)
    monkeypatch.setattr(
        providers.uuid,
        "uuid4",
        lambda: uuid.UUID("9da3ecf0-9791-47c5-968b-3f44318940d0"),
    )
    monkeypatch.setattr(
        providers,
        "_klyrow_token",
        lambda: pytest.fail("Telnexa submission requested a Klyrow token"),
    )
    monkeypatch.setattr(
        providers,
        "_klyrow_tls_context",
        lambda: pytest.fail("Telnexa submission requested Klyrow mTLS"),
    )
    return api_key, hmac_secret


def test_telnexa_provider_uses_gateway_body_and_hmac_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_key, hmac_secret = configure(tmp_path, monkeypatch)
    adapter_message_id = "18cd23b0-52bd-41d3-89f8-d276de79d254"
    requests = []

    def urlopen(request, *, timeout):
        requests.append(request)
        assert timeout == 5.0
        return Response(
            {
                "accepted": True,
                "adapter_message_id": adapter_message_id,
                "carrier_submitted": True,
                "duplicate": False,
                "state": "submitted",
            }
        )

    monkeypatch.setattr(providers.urllib.request, "urlopen", urlopen)
    result = providers.submit(production_message())

    assert result == providers.ProviderResult(
        adapter_message_id, "accepted", "submitted"
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == (
        "https://telnexa.internal.codestra.agency:8443/v1/messages"
    )
    assert request.method == "POST"
    payload = json.loads(request.data)
    assert payload == {
        "body": "bounded test",
        "correlation_id": "correlation-1",
        "customer_id": "customer-1",
        "idempotency_key": "idem-0001",
        "message_id": "ba6c50fa-2e38-41cb-b85b-8b153cb67ecf",
        "sender": "CODESTRA",
        "tenant_id": "tenant-a",
        "to": "+4915512345678",
    }
    assert request.data == json.dumps(
        payload, separators=(",", ":"), sort_keys=True
    ).encode()
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["authorization"] == "Bearer " + api_key.decode()
    assert headers["x-codestra-timestamp"] == "2000000000"
    assert headers["x-codestra-nonce"] == "9da3ecf0979147c5968b3f44318940d0"
    expected = hmac.new(
        hmac_secret,
        b"POST\n/v1/messages\n2000000000\n"
        b"9da3ecf0979147c5968b3f44318940d0\n"
        + request.data,
        hashlib.sha256,
    ).hexdigest()
    assert headers["x-codestra-signature"] == "sha256=" + expected


def test_telnexa_provider_does_not_promote_mock_receipt_to_acceptance(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        providers.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {
                "accepted": True,
                "adapter_message_id": "18cd23b0-52bd-41d3-89f8-d276de79d254",
                "carrier_submitted": False,
                "duplicate": False,
                "state": "mock_accepted",
            }
        ),
    )
    with pytest.raises(providers.ProviderError, match="delivery_not_authorized"):
        providers.submit(production_message())


def test_duplicate_submitting_receipt_preserves_ambiguous_delivery(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(tmp_path, monkeypatch)
    adapter_message_id = "18cd23b0-52bd-41d3-89f8-d276de79d254"
    monkeypatch.setattr(
        providers.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {
                "accepted": True,
                "adapter_message_id": adapter_message_id,
                "carrier_submitted": False,
                "duplicate": True,
                "state": "submitting",
            }
        ),
    )
    assert providers.submit(production_message()) == providers.ProviderResult(
        adapter_message_id,
        "deferred",
        "submitting",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://telnexa.internal.codestra.agency:8443/v1/messages",
        "https://telnexa.internal.codestra.agency:8443/v1/other",
        "https://user@telnexa.internal.codestra.agency:8443/v1/messages",
        "https://example.test/v1/messages",
    ],
)
def test_telnexa_provider_rejects_unapproved_endpoint(
    tmp_path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("TELNEXA_URL", url)
    monkeypatch.setattr(
        providers.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("unapproved endpoint reached"),
    )
    with pytest.raises(providers.ProviderError, match="provider_url_"):
        providers.submit(production_message())
