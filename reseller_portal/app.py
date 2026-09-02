from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, make_asgi_app

from .core import MemoryStore, PortalError, PortalService, hash_secret
from .persistence import PostgresState

repository = None
service = PortalService(MemoryStore())
HTTP_REQUESTS = Counter(
    "codestra_reseller_portal_http_requests_total",
    "Reseller portal HTTP requests by method, route, and status.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "codestra_reseller_portal_http_request_duration_seconds",
    "Reseller portal HTTP request duration by method and route.",
    ("method", "route"),
)


@asynccontextmanager
async def lifespan(app):
    global repository, service
    dsn=os.getenv("DATABASE_URL")
    if dsn:
        repository=PostgresState(dsn); service=PortalService(repository.load())
    elif os.getenv("PORTAL_REQUIRE_POSTGRES","true").lower()=="true":
        raise RuntimeError("DATABASE_URL is required")
    yield


app=FastAPI(title="Codestra Reseller Portal API",version="1.0",docs_url="/docs",redoc_url=None,lifespan=lifespan)

@app.middleware("http")
async def observe_request(request, call_next):
    started = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route_path, str(status_code)).inc()
        HTTP_DURATION.labels(request.method, route_path).observe(time.monotonic() - started)

class Credential(BaseModel): name:str=Field(min_length=2,max_length=80)
class Sender(BaseModel): value:str; sender_type:str; countries:list[str]; services:list[str]
class Domain(BaseModel): domain:str
class Webhook(BaseModel): url:str
class Subaccount(BaseModel): name:str; services:list[str]=["sms","email"]
class Limits(BaseModel): requests_per_minute:int=Field(ge=1,le=10000); usage_cap_minor:int=Field(ge=0); countries:list[str]=[]
class Switch(BaseModel): enabled:bool
class Kyc(BaseModel): business_identity:dict; document_metadata:list[dict]=[]
class Credit(BaseModel):
    tenant_id:str
    amount_minor:int=Field(gt=0)
    payment_provider:str=Field(min_length=2,max_length=80)
    transaction_id:str=Field(min_length=8,max_length=200)
class Invoice(BaseModel): period:str; amount_minor:int=Field(ge=0,default=0)
class Synthetic(BaseModel): channel:Literal["sms","email"]; reference:str

def persist():
    if repository: repository.save(service.s)

def fail(exc):
    raise HTTPException(404 if str(exc)=="not_found" else 422,str(exc))

def actor(session: str|None=Cookie(None,alias="codestra_session")):
    value=service.s.sessions.get(hash_secret(session or ""))
    if not value: raise HTTPException(401,"onboarding_assignment_required")
    user=service.s.users.get(value["user"])
    if not user or user.get("status")!="active": raise HTTPException(401,"session_revoked")
    return {**value,"role":user["role"]}

def allow(*roles):
    def check(a=Depends(actor)):
        if a["role"] not in roles: raise HTTPException(403,"role_denied")
        return a
    return check

@app.get("/livez")
def livez(): return {"status":"live"}
@app.get("/healthz")
def healthz(): return {"status":"live"}
@app.get("/readyz")
def readyz():
    if repository is None or not repository.ready():
        raise HTTPException(503,"database_unavailable")
    return {"status":"ready","database":"postgresql","live_sms":False,"live_email":False}
app.mount("/metrics", make_asgi_app())
@app.get("/")
def index(): return FileResponse(os.path.join(os.path.dirname(__file__),"static","index.html"))
@app.post("/v1/session")
def login(response:Response,x_auth_request_sub:str=Header(...),x_auth_request_email:str=Header(...),x_portal_gateway_secret:str=Header(...)):
    if not os.getenv("PORTAL_GATEWAY_SHARED_SECRET") or x_portal_gateway_secret!=os.environ["PORTAL_GATEWAY_SHARED_SECRET"]: raise HTTPException(401,"trusted_oidc_gateway_required")
    try: token=service.login(x_auth_request_sub)
    except PortalError as exc: raise HTTPException(403,str(exc))
    persist(); response.set_cookie("codestra_session",token,httponly=True,secure=True,samesite="strict",max_age=3600,path="/")
    return {"authenticated":True}
@app.delete("/v1/session",status_code=204)
def logout(response:Response,a=Depends(actor)):
    for key,value in list(service.s.sessions.items()):
        if value=={"user":a["user"],"tenant":a["tenant"]}: service.s.sessions.pop(key,None)
    service.audit(a["tenant"],a["user"],"logout","session"); persist(); response.delete_cookie("codestra_session",path="/")
@app.get("/v1/dashboard")
def dashboard(a=Depends(actor)): return service.dashboard(a["tenant"])
@app.post("/v1/credentials",status_code=201)
def credential(value:Credential,a=Depends(allow("owner","admin","developer"))): result=service.credential(a["tenant"],a["user"],value.name); persist(); return result
@app.post("/v1/credentials/{cid}/rotate",status_code=201)
def rotate(cid:str,idempotency_key:str=Header(...,alias="Idempotency-Key"),a=Depends(allow("owner","admin","developer"))):
    try: result=service.rotate(a["tenant"],a["user"],cid,idempotency_key); persist(); return result
    except PortalError as exc: fail(exc)
@app.delete("/v1/credentials/{cid}",status_code=204)
def revoke(cid:str,a=Depends(allow("owner","admin","developer"))):
    try: service.revoke(a["tenant"],a["user"],cid); persist()
    except PortalError as exc: fail(exc)
@app.post("/v1/senders",status_code=201)
def sender(value:Sender,a=Depends(allow("owner","admin","developer"))): result=service.sender(a["tenant"],a["user"],value.value,value.sender_type,value.countries,value.services); persist(); return result
@app.post("/v1/domains",status_code=201)
def domain(value:Domain,a=Depends(allow("owner","admin","developer"))): result=service.domain(a["tenant"],a["user"],value.domain); persist(); return result
@app.post("/v1/webhooks",status_code=201)
def webhook(value:Webhook,a=Depends(allow("owner","admin","developer"))):
    try: result=service.webhook(a["tenant"],a["user"],value.url); persist(); return result
    except PortalError as exc: fail(exc)
@app.post("/v1/webhooks/{wid}/test")
def webhook_test(wid:str,a=Depends(allow("owner","admin","developer"))):
    try: result=service.webhook_test(a["tenant"],a["user"],wid); persist(); return result
    except PortalError as exc: fail(exc)
@app.post("/v1/subaccounts",status_code=201)
def subaccount(value:Subaccount,a=Depends(allow("owner","admin"))): result=service.subaccount(a["tenant"],a["user"],value.name,value.services); persist(); return result
@app.put("/v1/limits")
def limits(value:Limits,a=Depends(allow("owner","admin"))): result=service.update_limits(a["tenant"],a["user"],**value.model_dump()); persist(); return result
@app.put("/v1/kill-switch")
def kill_switch(value:Switch,a=Depends(allow("owner","admin"))): result=service.set_kill_switch(a["tenant"],a["user"],value.enabled); persist(); return result
@app.post("/v1/kyc",status_code=201)
def kyc(value:Kyc,a=Depends(allow("owner","admin"))): result=service.kyc_submit(a["tenant"],a["user"],value.business_identity,value.document_metadata); persist(); return result
@app.post("/v1/internal/billing/credits",status_code=201)
def credit(value:Credit,x_portal_billing_secret:str=Header(...)):
    expected=os.getenv("PORTAL_BILLING_SHARED_SECRET","")
    if not expected or not __import__("secrets").compare_digest(x_portal_billing_secret,expected):
        raise HTTPException(401,"trusted_billing_authority_required")
    try:
        result=service.credit(value.tenant_id,"billing-authority",value.amount_minor,
                              value.payment_provider,value.transaction_id); persist(); return result
    except PortalError as exc: fail(exc)
@app.post("/v1/billing/invoices",status_code=201)
def invoice(value:Invoice,a=Depends(allow("owner","admin","billing"))): result=service.invoice(a["tenant"],a["user"],value.period,value.amount_minor); persist(); return result
@app.post("/v1/synthetic/messages",status_code=201)
def synthetic(value:Synthetic,a=Depends(allow("owner","admin","developer"))):
    try: result=service.synthetic_message(a["tenant"],a["user"],value.channel,value.reference); persist(); return result
    except PortalError as exc: fail(exc)
