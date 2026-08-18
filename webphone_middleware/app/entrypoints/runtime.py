"""Shared runtime controls for API and worker entrypoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, make_asgi_app

from app.core.auth import BearerAuthError, verify_bearer
from app.core.config import settings
from app.db.session import engine

logger = logging.getLogger("codestra.runtime")
WORKER_CYCLES = Counter(
    "codestra_worker_cycles_total", "Worker cycles", ["service", "result"]
)
WORKER_READY = Gauge("codestra_worker_ready", "Worker readiness", ["service"])
FEATURE_FLAG_STATE = Gauge(
    "codestra_feature_flag_state",
    "Canonical fail-closed feature flag state",
    ["service", "flag"],
)
CORRELATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RATE_WINDOWS: OrderedDict[str, deque[float]] = OrderedDict()
MAX_RATE_IDENTITIES = 4096
N8N_TRANSITION_PATH = re.compile(
    r"^/api/v1/n8n/executions/[0-9a-fA-F-]{36}/transitions$"
)


class JsonFormatter(logging.Formatter):
    """Small JSON formatter that never serializes arbitrary request bodies."""

    def format(self, record: logging.LogRecord) -> str:
        value = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": os.getenv("SERVICE_NAME", "codestra-middleware"),
        }
        for name in ("correlation_id", "queue", "result"):
            field = getattr(record, name, None)
            if field is not None:
                value[name] = str(field)
        if record.exc_info:
            value["exception"] = self.formatException(record.exc_info)
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


def validate_runtime(service: str, queue: str | None = None) -> None:
    settings.validate_safety()
    canonical_flags = {
        "send_events": settings.send_events,
        "broad_event_delivery_enabled": settings.broad_event_delivery_enabled,
        "production_n8n_enabled": settings.production_n8n_enabled,
        "n8n_production_workflows_enabled": (settings.n8n_production_workflows_enabled),
        "enable_external_delivery": settings.enable_external_delivery,
    }
    for flag, enabled in canonical_flags.items():
        FEATURE_FLAG_STATE.labels(service=service, flag=flag).set(int(enabled))
    logger.info(
        "canonical feature flags loaded",
        extra={"result": json.dumps(canonical_flags, sort_keys=True)},
    )
    expected = os.getenv("SERVICE_NAME")
    if expected and expected != service:
        raise RuntimeError(f"SERVICE_NAME must be {service}")
    if queue is not None:
        configured = os.getenv("QUEUE_NAME", queue)
        if configured != queue:
            raise RuntimeError(f"QUEUE_NAME must be {queue}")
    if service == "middleware-event-gateway" and not settings.auth_ready:
        raise RuntimeError("event gateway authorization configuration is incomplete")
    if service == "middleware-event-gateway":
        settings.quarantine_fingerprint_secret
        settings.quarantine_encryption_key
    if (
        service in {"middleware-integration-api", "middleware-policy-engine"}
        and not settings.middleware_secret
    ):
        raise RuntimeError(f"{service} authorization configuration is incomplete")
    if service == "middleware-integration-api":
        settings.quarantine_fingerprint_secret
        settings.quarantine_encryption_key
        settings.quarantine_reviewer_secret


def add_api_runtime(app: FastAPI, service: str) -> None:
    @app.middleware("http")
    async def request_controls(request: Request, call_next):
        try:
            content_length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return JSONResponse({"detail": "invalid content length"}, status_code=400)
        if content_length < 0:
            return JSONResponse({"detail": "invalid content length"}, status_code=400)
        if content_length > settings.request_max_bytes:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        signed_write = request.method == "POST" and (
            request.url.path
            in {
                "/api/v1/events/vicidial",
                "/api/v2/telephony/canary",
                "/api/v1/n8n/executions",
                "/api/v1/n8n/executions/register",
                "/api/v1/n8n/acknowledgements",
                "/api/v1/sales/scraper-results",
                "/api/v1/readiness/server-a/challenge",
                "/api/v1/integrations/breero/events",
            }
            or N8N_TRANSITION_PATH.fullmatch(request.url.path) is not None
        )
        if signed_write:
            identity = request.client.host if request.client else "unknown"
            now = time.monotonic()
            window = _RATE_WINDOWS.setdefault(identity, deque())
            _RATE_WINDOWS.move_to_end(identity)
            while len(_RATE_WINDOWS) > MAX_RATE_IDENTITIES:
                _RATE_WINDOWS.popitem(last=False)
            while window and window[0] < now - 60:
                window.popleft()
            limit = (
                settings.readiness_rate_limit_per_minute
                if request.url.path == "/api/v1/readiness/server-a/challenge"
                else settings.quarantine_rate_limit_per_minute
            )
            if len(window) >= limit:
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            window.append(now)
        correlation_id = str(uuid4())
        client_correlation = request.headers.get("x-correlation-id", "").strip()
        request.state.correlation_id = correlation_id
        request.state.client_correlation_id = (
            client_correlation if CORRELATION_RE.fullmatch(client_correlation) else None
        )
        signed_paths = {
            "/api/v1/events/vicidial",
            "/api/v1/automation/events",
            "/api/v2/telephony/canary",
            "/api/v1/n8n/executions",
            "/api/v1/n8n/executions/register",
            "/api/v1/n8n/acknowledgements",
            "/api/v1/n8n-runtime/results",
            "/api/v1/n8n-runtime/social-authorize",
            "/api/v1/sales/scraper-results",
            "/api/v1/readiness/server-a/challenge",
            "/api/v1/integrations/breero/events",
        }
        if (
            (
                request.url.path.startswith("/api/")
                or request.url.path.startswith("/v1/")
            )
            and request.url.path not in signed_paths
            and not signed_write
        ):
            try:
                verify_bearer(
                    request.headers.get("Authorization", ""),
                    settings.middleware_secret,
                )
            except BearerAuthError as exc:
                status_code = 503 if not settings.middleware_secret else 401
                return JSONResponse(
                    {"detail": str(exc)},
                    status_code=status_code,
                    headers={"X-Correlation-ID": correlation_id},
                )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["Traceparent"] = (
            request.headers.get("traceparent", "")
            or f"00-{uuid4().hex}-{uuid4().hex[:16]}-00"
        )
        return response

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @app.get("/readyz")
    async def readiness() -> dict[str, str]:
        return {
            "status": "ready",
            "service": service,
            "authorization": "online",
            "delivery": "disabled",
        }

    @app.get("/dependencies")
    async def dependencies() -> dict[str, object]:
        return {
            "service": service,
            "database": "configured",
            "redis": "configured",
            "live_writes_enabled": settings.live_writes_enabled,
            "odoo_delivery_enabled": settings.odoo_delivery_enabled,
            "n8n_delivery_enabled": settings.n8n_delivery_enabled,
            "send_events": settings.send_events,
            "broad_event_delivery_enabled": settings.broad_event_delivery_enabled,
            "production_n8n_enabled": settings.production_n8n_enabled,
            "n8n_production_workflows_enabled": (
                settings.n8n_production_workflows_enabled
            ),
            "enable_external_delivery": settings.enable_external_delivery,
            "broad_event_pipeline_enabled": settings.broad_event_pipeline_enabled,
        }

    app.mount("/metrics", make_asgi_app())


def run_api(app: FastAPI, service: str) -> None:
    configure_logging()
    validate_runtime(service)
    # Container ingress is restricted by the private Docker network.
    uvicorn.run(
        app,
        host="0.0.0.0",  # nosec B104
        port=int(os.getenv("PORT", "8095")),
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


Cycle = Callable[[], Awaitable[dict[str, object]]]


class WorkerState(TypedDict):
    ready: bool
    stopping: bool
    last_success: str | None
    last_error: str | None


def worker_app(service: str, queue: str, cycle: Cycle) -> FastAPI:
    state: WorkerState = {
        "ready": False,
        "stopping": False,
        "last_success": None,
        "last_error": None,
    }

    async def loop() -> None:
        interval = max(1, int(os.getenv("WORKER_INTERVAL_SECONDS", "30")))
        state["ready"] = True
        WORKER_READY.labels(service).set(1)
        while not state["stopping"]:
            try:
                result = await cycle()
                state["last_success"] = datetime.now(UTC).isoformat()
                state["last_error"] = None
                WORKER_CYCLES.labels(service, "success").inc()
                logger.info(
                    "worker_cycle_complete",
                    extra={"queue": queue, "result": result},
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["last_error"] = type(exc).__name__
                WORKER_CYCLES.labels(service, "error").inc()
                logger.exception("worker_cycle_failed", extra={"queue": queue})
            await asyncio.sleep(interval)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(loop(), name=f"{service}-loop")
        try:
            yield
        finally:
            state["stopping"] = True
            state["ready"] = False
            WORKER_READY.labels(service).set(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await engine.dispose()

    app = FastAPI(title=service, lifespan=lifespan)

    @app.get("/healthz")
    async def health() -> dict[str, object]:
        return {"status": "ok", "service": service, "stopping": state["stopping"]}

    @app.get("/readyz")
    async def ready() -> dict[str, object]:
        return {
            "status": "ready" if state["ready"] else "not-ready",
            "service": service,
            "queue": queue,
            "last_success": state["last_success"],
            "last_error": state["last_error"],
        }

    @app.get("/dependencies")
    async def dependencies() -> dict[str, object]:
        return {
            "database": "configured",
            "redis": "configured",
            "queue": queue,
            "live_writes_enabled": settings.live_writes_enabled,
        }

    app.mount("/metrics", make_asgi_app())
    return app


def run_worker(service: str, queue: str, cycle: Cycle) -> None:
    configure_logging()
    validate_runtime(service, queue)
    app = worker_app(service, queue, cycle)
    # Container ingress is restricted by the private Docker network.
    uvicorn.run(
        app,
        host="0.0.0.0",  # nosec B104
        port=int(os.getenv("PORT", "8095")),
        access_log=False,
    )
