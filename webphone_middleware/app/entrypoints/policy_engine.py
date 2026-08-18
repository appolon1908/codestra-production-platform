"""Codestra canonical policy API runtime."""

from fastapi import FastAPI

from app.api.v1.policy_engine import router
from app.entrypoints.runtime import add_api_runtime, run_api


SERVICE = "middleware-policy-engine"
app = FastAPI(title="Codestra Policy Engine", version="1.0.0")
app.include_router(router)
add_api_runtime(app, SERVICE)


if __name__ == "__main__":
    run_api(app, SERVICE)
