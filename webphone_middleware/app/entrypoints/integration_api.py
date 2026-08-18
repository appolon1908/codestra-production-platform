"""Authenticated integration and control surface."""

from fastapi import FastAPI

from app.api.v1.automation import router as automation_router
from app.api.v1.commands import router as commands_router
from app.api.v1.control import router as control_router
from app.api.v1.lead_reconciliation import router as lead_reconciliation_router
from app.api.v1.lead_automation import router as lead_automation_router
from app.api.v1.mappings import router as mappings_router
from app.api.v1.n8n_staging import router as n8n_staging_router
from app.api.v1.n8n_transport import router as n8n_transport_router
from app.api.v1.n8n_runtime import router as n8n_runtime_router
from app.api.v1.operations import router as operations_router
from app.api.v1.orchestration import router as orchestration_router
from app.api.v1.quarantine import router as quarantine_router
from app.api.v1.reports import router as reports_router
from app.api.v1.telephony import router as telephony_router
from app.api.v1.sales import router as sales_router
from app.api.v1.booking import router as booking_router
from app.api.v1.webphone import router as webphone_router
from app.entrypoints.runtime import add_api_runtime, run_api

SERVICE = "middleware-integration-api"
routers = (
    commands_router,
    control_router,
    automation_router,
    reports_router,
    operations_router,
    lead_reconciliation_router,
    lead_automation_router,
    orchestration_router,
    mappings_router,
    webphone_router,
    n8n_staging_router,
    n8n_transport_router,
    n8n_runtime_router,
    quarantine_router,
    telephony_router,
    sales_router,
    booking_router,
)
app = FastAPI(
    title="Codestra Integration API",
    version="1.0.0",
    routes=[
        route
        for router in routers
        for route in router.routes
        if not (getattr(route, "path", "") or "").startswith("/api/v1/events/")
    ],
)
add_api_runtime(app, SERVICE)


if __name__ == "__main__":
    run_api(app, SERVICE)
