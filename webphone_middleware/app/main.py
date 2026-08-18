import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.api.v1.automation import router as automation_router
from app.api.v1.campaign_search import router as campaign_search_router
from app.api.v1.commands import router as commands_router
from app.api.v1.control import router as control_router
from app.api.v1.events import router as events_router
from app.api.v1.lead_reconciliation import router as lead_reconciliation_router
from app.api.v1.lead_automation import router as lead_automation_router
from app.api.v1.mappings import router as mappings_router
from app.api.v1.n8n_staging import router as n8n_staging_router
from app.api.v1.n8n_target import router as n8n_target_router
from app.api.v1.n8n_transport import router as n8n_transport_router
from app.api.v1.n8n_runtime import router as n8n_runtime_router
from app.api.v1.operations import router as operations_router
from app.api.v1.orchestration import router as orchestration_router
from app.api.v1.publisher import router as publisher_router
from app.api.v1.reports import router as reports_router
from app.api.v1.registry import router as registry_router
from app.api.v1.recordings import router as recordings_router
from app.api.v1.sales import router as sales_router
from app.api.v1.social import router as social_router
from app.api.v1.telephony import router as telephony_router
from app.api.internal.ai_jobs import router as internal_ai_jobs_router
from app.api.v1.ai_console import router as ai_console_router
from app.api.v1.tts import router as tts_router
from app.api.v1.tts import validate_readiness as validate_tts_readiness
from app.api.v1.ai_commands import router as ai_commands_router
from app.api.v1.webphone import router as webphone_router
from app.api.v1.agent_realtime import router as agent_realtime_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.orders import router as orders_router
from app.api.v1.ai import router as ai_router
from app.api.v1.provider_commands import router as provider_commands_router
from app.integrations.postiz.routes import router as postiz_router
from app.core.auth import BearerAuthError, verify_bearer
from app.core.config import settings

app = FastAPI(title="Codestra Middleware", version="0.2.0")
app.include_router(events_router)
app.include_router(control_router)
app.include_router(automation_router)
app.include_router(reports_router)
app.include_router(operations_router)
app.include_router(lead_reconciliation_router)
app.include_router(lead_automation_router)
app.include_router(orchestration_router)
app.include_router(mappings_router)
app.include_router(publisher_router)
app.include_router(webphone_router)
app.include_router(agent_realtime_router)
app.include_router(n8n_staging_router)
app.include_router(n8n_transport_router)
app.include_router(n8n_runtime_router)
app.include_router(n8n_target_router)
app.include_router(telephony_router)
app.include_router(internal_ai_jobs_router)
app.include_router(ai_console_router)
app.include_router(tts_router)
app.include_router(ai_commands_router)
app.include_router(orders_router)
app.include_router(ai_router)
app.include_router(provider_commands_router)
app.include_router(integrations_router)
app.include_router(postiz_router)
app.include_router(campaign_search_router)
app.include_router(registry_router)
app.include_router(commands_router)
app.include_router(recordings_router)
app.include_router(sales_router)
app.include_router(social_router)
app.mount("/metrics", make_asgi_app())


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/v1/sales/"):
        correlation_id = request.headers.get("X-Correlation-ID", "") or "generated"
        return JSONResponse(
            {
                "code": "INVALID_LEAD_CANDIDATE",
                "message": "sales request validation failed",
                "correlation_id": correlation_id,
                "retryable": False,
            },
            status_code=422,
            headers={"X-Correlation-ID": correlation_id},
        )
    return await request_validation_exception_handler(request, exc)


SIGNED_WEBHOOK_PATHS = frozenset(
    {
        "/api/v1/events/vicidial",
        "/api/v1/automation/events",
        "/api/v2/telephony/canary",
        "/api/v1/n8n/executions",
        "/api/v1/n8n/executions/register",
        "/api/v1/n8n/acknowledgements",
        "/api/v1/n8n-runtime/results",
        "/api/v1/lead-automation/results",
        "/api/v1/registry/resolve",
        "/api/v1/sales/scraper-results",
    }
)
SELF_AUTHENTICATED_PATHS = frozenset({"/v1/registry/search"})
SOCIAL_WEBHOOK_PATH = re.compile(r"^/api/v1/social/webhooks/(?:postly|hootsuite)$")
AI_CONSOLE_SELF_AUTHENTICATED_PATHS = (
    ("POST", re.compile(r"^/api/v1/ai/conversations$")),
    (
        "POST",
        re.compile(r"^/api/v1/ai/conversations/[0-9a-fA-F-]{36}/messages$"),
    ),
    ("GET", re.compile(r"^/api/v1/ai/jobs/[0-9a-fA-F-]{36}/stream$")),
    ("POST", re.compile(r"^/api/v1/ai/jobs/[0-9a-fA-F-]{36}/cancel$")),
    ("POST", re.compile(r"^/api/v1/ai/commands$")),
    ("GET", re.compile(r"^/api/v1/ai/commands/[0-9a-fA-F-]{36}$")),
    ("GET", re.compile(r"^/api/v1/ai/commands/[0-9a-fA-F-]{36}/result$")),
    (
        "POST",
        re.compile(r"^/api/v1/ai/commands/[0-9a-fA-F-]{36}/(?:cancel|approve|reject)$"),
    ),
    ("GET", re.compile(r"^/api/v1/ai/(?:capabilities|usage)$")),
    ("POST", re.compile(r"^/api/v1/ai/tts/stream$")),
)
N8N_TRANSITION_PATH = re.compile(
    r"^/api/v1/n8n/executions/[0-9a-fA-F-]{36}/transitions$"
)
RECORDING_EXPORTER_PATH = re.compile(
    r"^/api/v1/recordings(?:/reservations|/REC-[0-9a-f]{32}/(?:complete|failure))$"
)


def _is_ai_console_jwt_route(request: Request) -> bool:
    return any(
        request.method == method and path.fullmatch(request.url.path)
        for method, path in AI_CONSOLE_SELF_AUTHENTICATED_PATHS
    )


@app.middleware("http")
async def control_request_guard(request: Request, call_next):
    content_length = int(request.headers.get("content-length", "0") or 0)
    if (
        request.method == "POST"
        and request.url.path.startswith("/api/v1/sales/")
        and request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        correlation_id = request.headers.get("X-Correlation-ID", "") or "generated"
        return JSONResponse(
            {
                "code": "INVALID_CONTENT_TYPE",
                "message": "application/json is required",
                "correlation_id": correlation_id,
                "retryable": False,
            },
            status_code=415,
        )
    if (
        request.url.path.startswith("/api/v1/sales/")
        and content_length > settings.sales_lead_request_max_bytes
    ):
        correlation_id = request.headers.get("X-Correlation-ID", "") or "generated"
        return JSONResponse(
            {
                "code": "REQUEST_TOO_LARGE",
                "message": "request exceeds the sales intake limit",
                "correlation_id": correlation_id,
                "retryable": False,
            },
            status_code=413,
        )
    if content_length > settings.request_max_bytes:
        return JSONResponse({"detail": "request too large"}, status_code=413)
    if (
        (request.url.path.startswith("/api/") or request.url.path.startswith("/v1/"))
        and request.url.path not in SIGNED_WEBHOOK_PATHS
        and not RECORDING_EXPORTER_PATH.fullmatch(request.url.path)
        and not (
            request.method == "POST" and N8N_TRANSITION_PATH.fullmatch(request.url.path)
        )
        and request.url.path not in SELF_AUTHENTICATED_PATHS
        and not (request.method == "POST" and SOCIAL_WEBHOOK_PATH.fullmatch(request.url.path))
        and not _is_ai_console_jwt_route(request)
    ):
        try:
            verify_bearer(
                request.headers.get("Authorization", ""), settings.middleware_secret
            )
        except BearerAuthError as exc:
            status_code = 503 if not settings.middleware_secret else 401
            return JSONResponse({"detail": str(exc)}, status_code=status_code)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = (
        request.headers.get("X-Correlation-ID", "") or "generated"
    )
    return response


@app.get("/healthz")
@app.get("/health")
@app.get("/health/live")
async def healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "mode": "dry-run",
        "authorization": "online" if settings.auth_ready else "offline",
    }


@app.get("/readyz", response_model=None)
@app.get("/readiness", response_model=None)
@app.get("/health/ready", response_model=None)
async def readyz() -> dict[str, str] | JSONResponse:
    if not settings.auth_ready:
        return JSONResponse(
            {"status": "not-ready", "authorization": "offline"}, status_code=503
        )
    if settings.elevenlabs_provider_enabled:
        try:
            validate_tts_readiness()
        except HTTPException:
            return JSONResponse(
                {"status": "not-ready", "tts": "unavailable"}, status_code=503
            )
    return {"status": "ready", "integration": "outbox-only", "authorization": "online"}


@app.get("/.well-known/codestra-service")
async def service_identity() -> dict[str, object]:
    return {
        "service": "codestra-recording-api",
        "contract_version": "1.0",
        "hostname": "api.staging.internal.codestra.agency",
        "tls_sni_required": True,
    }


@app.get("/version")
async def version() -> dict[str, str]:
    return {
        "service": "codestra-contact-center-middleware",
        "version": "1.0.0",
        "environment": settings.environment,
    }
