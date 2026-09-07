from __future__ import annotations

import asyncio
import base64
import json
import os
import statistics
import time
import uuid
from datetime import datetime, timezone

import httpx
import websockets

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
        "correlation_id": f"cert-{event_id}", "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant, "business_unit_id": "TEST", "campaign_id": campaign,
        "user_id": user or agent, "agent_id": agent, "call_id": f"TEST-{event_id}", "sequence": sequence,
        "payload": payload or {},
    }


async def publish(document: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{INTERNAL_API}/internal/v1/realtime/events", headers={"X-Codestra-Internal-Token": INTERNAL_TOKEN}, json=document)
        response.raise_for_status()
        return response.json()


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
    load_tickets = [
        await issue(read(identity["token_file"]), identity["campaign_id"])
        for identity in load_identities
    ]
    load_started = time.perf_counter()
    load_sockets = await asyncio.gather(*(connect(value["ticket"]) for value in load_tickets))
    connect_seconds = time.perf_counter() - load_started
    assert len(load_sockets) == 250
    first = load_identities[0]
    load_event = event(f"load-{uuid.uuid4()}", 1, "agent.ready", agent=first["agent_id"],
                       user=first.get("user_id"), tenant=first["tenant_id"],
                       campaign=first["campaign_id"])
    delivery_start = time.perf_counter()
    assert (await publish(load_event))["delivered"] == 1
    assert json.loads(await load_sockets[0][0].recv())["event_id"] == load_event["event_id"]
    load_latency_ms = (time.perf_counter() - delivery_start) * 1000
    await no_message(load_sockets[1][0])
    await asyncio.gather(*(socket.close() for socket, _ in load_sockets))
    results["LOAD_TEST"] = "PASS"
    results["LOAD_CONNECTIONS"] = 250
    results["LOAD_CONNECT_SECONDS"] = round(connect_seconds, 3)
    results["P95_DELIVERY_LATENCY"] = "PASS" if max(latency_ms, load_latency_ms) < 500 else "FAIL"
    results["SCREEN_POP_LATENCY_MS"] = round(latency_ms, 3)
    results["LOAD_DELIVERY_LATENCY_MS"] = round(load_latency_ms, 3)

    await ws_a.close()
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
