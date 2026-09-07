from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
import nats
import websockets

try:
    from .certification_latency import canonical_calling_envelope, latency_summary, measure_delivery_batch, validate_load_scopes
except ImportError:  # Support the documented direct script invocation.
    from certification_latency import canonical_calling_envelope, latency_summary, measure_delivery_batch, validate_load_scopes

PUBLIC_API = os.getenv("PUBLIC_API", "https://api.codestra.agency")
PUBLIC_WS = os.getenv("PUBLIC_WS", "wss://api.codestra.agency/ws/agent")
INTERNAL_API = os.getenv("INTERNAL_API", "http://codestra-websocket-gateway-gateway-1:8080")
ORIGIN = "https://phone.codestra.agency"


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


INTERNAL_TOKEN = read(os.environ["INTERNAL_TOKEN_FILE"])
CLIENT_SECRET = read(os.environ["CERTIFIER_CLIENT_SECRET_FILE"])
CERTIFIER_TENANT_ID = os.environ["CERTIFIER_TENANT_ID"]
CERTIFIER_AGENT_ID = os.environ["CERTIFIER_AGENT_ID"]
CERTIFIER_CAMPAIGN_ID = os.getenv("CERTIFIER_CAMPAIGN_ID", "TEST_SYN")
CERTIFIER_NATS_URL = os.getenv("CERTIFIER_NATS_URL", "tls://codestra-nats:4222")
CERTIFIER_NATS_CREDENTIALS_FILE = os.environ["CERTIFIER_NATS_CREDENTIALS_FILE"]


async def token() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "https://auth.codestra.agency/realms/codestra/protocol/openid-connect/token",
            data={"grant_type": "client_credentials", "client_id": "codestra-realtime-certifier", "client_secret": CLIENT_SECRET},
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def issue(access_token: str, campaign_id: str = "TEST_SYN", resume_cursor: int = 0) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        request_id = str(uuid.uuid4())
        response = await client.post(
            f"{PUBLIC_API}/api/v1/realtime/sessions",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Idempotency-Key": request_id,
                "X-Correlation-ID": request_id,
            },
            json={"campaign_id": campaign_id, "resume_cursor": resume_cursor},
        )
        response.raise_for_status()
        return response.json()


async def connect(ticket: str, last_event_id: str | None = None):
    websocket = await websockets.connect(PUBLIC_WS, origin=ORIGIN, open_timeout=10, max_size=65536, ping_interval=25, ping_timeout=10)
    frame = {"type": "auth", "ticket": ticket}
    if last_event_id:
        frame["last_event_id"] = last_event_id
    await websocket.send(json.dumps(frame))
    authenticated = json.loads(await asyncio.wait_for(websocket.recv(), 10))
    assert authenticated["type"] == "authenticated", authenticated
    return websocket, authenticated


def event(event_id: str, sequence: int, kind: str, *, agent: str = CERTIFIER_AGENT_ID, user: str | None = None,
          tenant: str = CERTIFIER_TENANT_ID, campaign: str = CERTIFIER_CAMPAIGN_ID, payload: dict | None = None) -> dict:
    return {
        "event_id": event_id, "schema_version": "1.0", "type": kind,
        "correlation_id": str(uuid.uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant, "business_unit_id": "TEST", "campaign_id": campaign,
        "user_id": user or agent, "agent_id": agent, "call_id": str(uuid.uuid4()), "sequence": sequence,
        "payload": payload or {},
    }


async def publish(document: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{INTERNAL_API}/internal/v1/realtime/events", headers={"X-Codestra-Internal-Token": INTERNAL_TOKEN}, json=document)
        response.raise_for_status()
        return response.json()


async def publish_jetstream(document: dict, jetstream=None) -> int:
    subject, envelope = canonical_calling_envelope(document)
    # The load test reuses its authenticated JetStream connection. Do not merge
    # arbitrary UI payload keys over the canonical identity fields.
    if jetstream is not None:
        ack = await jetstream.publish(subject, json.dumps(envelope).encode(), headers={"Nats-Msg-Id": document["event_id"]})
        return int(ack.seq)
    client = await nats.connect(
        servers=[CERTIFIER_NATS_URL], user_credentials=CERTIFIER_NATS_CREDENTIALS_FILE,
        connect_timeout=3, max_reconnect_attempts=3,
    )
    try:
        ack = await client.jetstream().publish(
            subject, json.dumps(envelope).encode(),
            headers={"Nats-Msg-Id": document["event_id"]},
        )
        return int(ack.seq)
    finally:
        await client.close()


async def no_message(websocket, seconds: float = 0.35) -> None:
    try:
        value = await asyncio.wait_for(websocket.recv(), seconds)
    except asyncio.TimeoutError:
        return
    raise AssertionError(f"unexpected cross-scope delivery: {value}")


async def main() -> None:
    results: dict[str, str | float | int] = {}
    access_token = await token()
    token_subject = json.loads(
        base64.urlsafe_b64decode(access_token.split(".")[1] + "==")
    )["sub"]

    async with httpx.AsyncClient(timeout=10) as client:
        invalid = await client.post(f"{PUBLIC_API}/api/v1/realtime/sessions", headers={"Authorization": "Bearer expired.invalid.token"})
        assert invalid.status_code == 401
    results["EXPIRED_AUTH"] = "PASS"

    issued = await issue(access_token, CERTIFIER_CAMPAIGN_ID)
    assert 30 <= (datetime.fromisoformat(issued["expires_at"]) - datetime.now(timezone.utc)).total_seconds() <= 60
    results["KEYCLOAK_AUTH"] = results["REALTIME_TICKET_ISSUANCE"] = "PASS"
    ws_a, _ = await connect(issued["ticket"])

    jetstream_id = str(uuid.uuid4())
    await publish_jetstream(event(jetstream_id, 1, "call.ringing", user=token_subject))
    jetstream_received = json.loads(await asyncio.wait_for(ws_a.recv(), 5))
    assert jetstream_received["event_id"] == jetstream_id
    assert jetstream_received["cursor"] >= 1
    results["JETSTREAM_END_TO_END"] = "PASS"

    ring_id = f"ring-{uuid.uuid4()}"
    started = time.perf_counter()
    accepted = await publish(event(ring_id, 1, "call.ringing", user=token_subject, payload={"direction": "inbound", "customer_name": "Synthetic Customer", "campaign": "TEST_SYN", "phone": "+1XXXXXXXXXX", "lead_id": "SYNTHETIC-LEAD-6101"}))
    received = json.loads(await asyncio.wait_for(ws_a.recv(), 5))
    latency_ms = (time.perf_counter() - started) * 1000
    assert accepted["delivered"] == 1 and received["event_id"] == ring_id
    results["SCREEN_POP_WEBSOCKET"] = "PASS"

    duplicate = await publish(event(ring_id, 1, "call.ringing", user=token_subject))
    assert duplicate["duplicate"] is True
    await no_message(ws_a)
    results["DUPLICATE_EVENT_PROTECTION"] = "PASS"

    recording_started = f"recording-started-{uuid.uuid4()}"
    await publish(event(recording_started, 2, "recording.started", user=token_subject, payload={"state": "ON"}))
    assert json.loads(await ws_a.recv())["type"] == "recording.started"
    recording_available = f"recording-available-{uuid.uuid4()}"
    await publish(event(recording_available, 3, "recording.available", user=token_subject, payload={"state": "available", "recording_id": "SYNTHETIC-REC-1"}))
    assert json.loads(await ws_a.recv())["type"] == "recording.available"
    results["RECORDING_WEBSOCKET"] = "PASS"

    event_a = event(f"isolation-a-{uuid.uuid4()}", 4, "call.ringing", user=token_subject)
    assert (await publish(event_a))["delivered"] == 1
    assert json.loads(await ws_a.recv())["event_id"] == event_a["event_id"]
    other_agent = event(f"isolation-b-{uuid.uuid4()}", 4, "call.ringing",
                        agent=f"{CERTIFIER_AGENT_ID}-OTHER", user=token_subject)
    assert (await publish(other_agent))["delivered"] == 0
    await no_message(ws_a)
    results["CROSS_AGENT_ISOLATION"] = "PASS"

    wrong_tenant = event(f"wrong-tenant-{uuid.uuid4()}", 1, "call.ringing", tenant="other-tenant", user=token_subject)
    wrong_campaign = event(f"wrong-campaign-{uuid.uuid4()}", 5, "call.ringing", campaign="OTHER_CAMPAIGN", user=token_subject)
    assert (await publish(wrong_tenant))["delivered"] == 0
    assert (await publish(wrong_campaign))["delivered"] == 0
    await no_message(ws_a)
    results["CROSS_TENANT_ISOLATION"] = results["WRONG_CAMPAIGN_ISOLATION"] = "PASS"

    await ws_a.close()
    replay_two = event(f"replay-2-{uuid.uuid4()}", 6, "call.answered", user=token_subject)
    replay_three = event(f"replay-3-{uuid.uuid4()}", 7, "call.connected", user=token_subject)
    await publish(replay_two); await publish(replay_three)
    resumed = await issue(access_token, CERTIFIER_CAMPAIGN_ID)
    ws_a, authenticated = await connect(resumed["ticket"], event_a["event_id"])
    replayed = [json.loads(await ws_a.recv()), json.loads(await ws_a.recv())]
    assert [item["event_id"] for item in replayed] == [replay_two["event_id"], replay_three["event_id"]]
    results["RECONNECT"] = results["REPLAY_AFTER_RECONNECT"] = "PASS"

    try:
        replay_socket = await websockets.connect(PUBLIC_WS, origin=ORIGIN)
        await replay_socket.send(json.dumps({"type": "auth", "ticket": resumed["ticket"]}))
        await replay_socket.recv()
        raise AssertionError("ticket replay accepted")
    except websockets.ConnectionClosed as closed:
        assert closed.code == 4401
    results["TICKET_SINGLE_USE"] = "PASS"

    try:
        invalid_socket = await websockets.connect(PUBLIC_WS, origin=ORIGIN)
        await invalid_socket.send(json.dumps({"type": "auth", "ticket": "invalid"}))
        await invalid_socket.recv()
        raise AssertionError("invalid ticket accepted")
    except websockets.ConnectionClosed as closed:
        assert closed.code == 4401
    results["INVALID_TICKET"] = "PASS"

    try:
        timeout_socket = await websockets.connect(PUBLIC_WS, origin=ORIGIN)
        await timeout_socket.recv()
        raise AssertionError("unauthenticated socket retained")
    except websockets.ConnectionClosed as closed:
        assert closed.code == 4408
    results["AUTH_TIMEOUT"] = "PASS"

    # Every load identity must be provisioned by the canonical authority. The
    # manifest is an audited JSON array of token_file/tenant_id/campaign_id/agent_id.
    load_manifest = json.loads(read(os.environ["CERTIFIER_LOAD_IDENTITIES_FILE"]))
    assert isinstance(load_manifest, list) and len(load_manifest) >= 250
    load_identities = load_manifest[:250]
    validate_load_scopes(load_identities)
    load_tickets = [
        await issue(read(identity["token_file"]), identity["campaign_id"])
        for identity in load_identities
    ]
    load_sockets = []
    opening = []
    nats_client = None

    async def open_one(value):
        socket, authenticated = await connect(value["ticket"])
        load_sockets.append(socket)
        return socket

    try:
        load_started = time.perf_counter()
        opening = [asyncio.create_task(open_one(value)) for value in load_tickets]
        ordered_sockets = await asyncio.gather(*opening)
        connect_seconds = time.perf_counter() - load_started
        nats_client = await nats.connect(
            servers=[CERTIFIER_NATS_URL], user_credentials=CERTIFIER_NATS_CREDENTIALS_FILE,
            connect_timeout=3, max_reconnect_attempts=3,
        )
        jetstream = nats_client.jetstream()
        documents = [
            event(str(uuid.uuid4()), 1, "agent.ready", agent=identity["agent_id"],
                  user=identity.get("user_id"), tenant=identity["tenant_id"],
                  campaign=identity["campaign_id"])
            for identity in load_identities
        ]
        async def publish_load(document):
            return await publish_jetstream(document, jetstream)
        samples = await measure_delivery_batch(ordered_sockets, documents, publish_load)
        results.update(latency_summary(samples))
        results["LOAD_TEST"] = results["P95_DELIVERY_LATENCY"]
        results["LOAD_CONNECTIONS"] = len(ordered_sockets)
        results["LOAD_CONNECT_SECONDS"] = round(connect_seconds, 3)
        # This older smoke measurement uses internal HTTP, not JetStream.
        results["INTERNAL_HTTP_SCREEN_POP_LATENCY_MS"] = round(latency_ms, 3)
    finally:
        for task in opening:
            if not task.done():
                task.cancel()
        await asyncio.gather(*opening, return_exceptions=True)
        await asyncio.gather(*(socket.close() for socket in load_sockets), return_exceptions=True)
        if nats_client is not None:
            await nats_client.close()

    await ws_a.close()
    print(json.dumps(results, indent=2, sort_keys=True))
    if results.get("P95_DELIVERY_LATENCY") != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
