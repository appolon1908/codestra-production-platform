from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .core import MemoryStore, PortalError, PortalService, hash_secret
from .persistence import PostgresState

repository = None
service = PortalService(MemoryStore())


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

class Credential(BaseModel): name:str=Field(min_length=2,max_length=80)
class Sender(BaseModel): value:str; sender_type:str; countries:list[str]; services:list[str]
class Domain(BaseModel): domain:str
class Webhook(BaseModel): url:str
class Subaccount(BaseModel): name:str; services:list[str]=["sms","email"]
class Limits(BaseModel): requests_per_minute:int=Field(ge=1,le=10000); usage_cap_minor:int=Field(ge=0); countries:list[str]=[]
class Switch(BaseModel): enabled:bool
class Kyc(BaseModel): business_identity:dict; document_metadata:list[dict]=[]
class Credit(BaseModel): amount_minor:int=Field(gt=0); reference:str
class Invoice(BaseModel): period:str; amount_minor:int=Field(ge=0,default=0)
class Synthetic(BaseModel): channel:Literal["sms","email"]; reference:str

def persist():
    if repository: repository.save(service.s)

def fail(exc):
    raise HTTPException(404 if str(exc)=="not_found" else 422,str(exc))

def actor(session: str|None=Cookie(None,alias="codestra_session"),x_auth_request_user:str|None=Header(None),x_auth_request_email:str|None=Header(None)):
    value=service.s.sessions.get(hash_secret(session or ""))
    if not value and x_auth_request_user:
        user=next((u for u in service.s.users.values() if u["subject"]==x_auth_request_user and u.get("status")=="active"),None)
        if user: value={"user":user["id"],"tenant":user["tenant_id"]}
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
@app.get("/readyz")
def readyz(): return {"status":"ready" if repository else "degraded","database":"postgresql" if repository else "memory","live_sms":False,"live_email":False}
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
def rotate(cid:str,a=Depends(allow("owner","admin","developer"))):
    try: result=service.rotate(a["tenant"],a["user"],cid); persist(); return result
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
@app.post("/v1/billing/credits",status_code=201)
def credit(value:Credit,a=Depends(allow("owner","admin","billing"))): result=service.credit(a["tenant"],a["user"],value.amount_minor,value.reference); persist(); return result
@app.post("/v1/billing/invoices",status_code=201)
def invoice(value:Invoice,a=Depends(allow("owner","admin","billing"))): result=service.invoice(a["tenant"],a["user"],value.period,value.amount_minor); persist(); return result
@app.post("/v1/synthetic/messages",status_code=201)
def synthetic(value:Synthetic,a=Depends(allow("owner","admin","developer"))):
    try: result=service.synthetic_message(a["tenant"],a["user"],value.channel,value.reference); persist(); return result
    except PortalError as exc: fail(exc)
