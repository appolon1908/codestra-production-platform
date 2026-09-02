#!/usr/bin/env python3
"""Exercise every private integration gateway route with synthetic events."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

CONTAINER = os.getenv("PRIVATE_GATEWAY_AUDIT_CONTAINER", "private-integration-gateway-1")
ROUTES = {
    "kyqra": ["/api/v1/kyqra/jobs", "/api/v1/kyqra/results", "/api/v1/kyqra/progress", "/api/v1/kyqra/failures"],
    "telnexa": ["/api/v1/telnexa/inbound", "/api/v1/telnexa/dlr", "/api/v1/telnexa/failure", "/api/v1/telnexa/provider-status"],
    "klyrow": ["/api/v1/klyrow/campaigns", "/api/v1/klyrow/contacts", "/api/v1/klyrow/events", "/api/v1/klyrow/bounces", "/api/v1/klyrow/complaints", "/api/v1/klyrow/unsubscribes"],
}


def call(method, path, body=None, headers=None):
    raw=b"" if body is None else json.dumps(body,separators=(",",":")).encode(); hdr=dict(headers or {})
    if raw: hdr.update({"Content-Type":"application/json","Content-Length":str(len(raw))})
    conn=http.client.HTTPConnection("127.0.0.1",8080,timeout=5); conn.request(method,path,raw or None,hdr); response=conn.getresponse(); data=response.read(); conn.close()
    try: value=json.loads(data or b"{}")
    except json.JSONDecodeError: value={"body_sha256":hashlib.sha256(data).hexdigest()}
    return response.status,value


def headers(system,event_id,body,stamp=None,bad=False):
    timestamp=str(stamp if stamp is not None else int(time.time())); raw=json.dumps(body,separators=(",",":")).encode()
    prefix={"kyqra":"X-Kyqra","telnexa":"X-Telnexa","klyrow":"X-Klyrow"}[system]
    canonical=timestamp.encode()+b"\n"+event_id.encode()+b"\n"+system.encode()+b"\n"+raw
    signature=hmac.new(os.environ[system.upper()+"_WEBHOOK_SECRET"].encode(),canonical,hashlib.sha256).hexdigest()
    if bad: signature="0"*64
    return {"Authorization":"Bearer "+os.environ[system.upper()+"_MIDDLEWARE_API_KEY"],prefix+"-Timestamp":timestamp,prefix+"-Event-Id":event_id,prefix+"-Signature":"sha256="+signature,"X-Source-System":system}


def record(items,name,actual,expected,evidence=None):
    items.append({"test":name,"status":"PASS" if actual==expected else "FAIL","http_status":actual,"expected":[expected],"evidence":evidence or {}})


def inside():
    run=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8]; items=[]
    for path in ("/health","/api/v1/kyqra/health","/api/v1/telnexa/health","/api/v1/klyrow/health"):
        status,value=call("GET",path); record(items,"private gateway "+path,status,200,{"response":value})
    metrics_headers={"Authorization":"Bearer "+os.environ["TELNEXA_MIDDLEWARE_API_KEY"],"X-Client-Certificate-Verified":"SUCCESS","X-Service-Identity":"telnexa","X-Service-Scope":"metrics:read"}
    status,value=call("GET","/metrics",headers=metrics_headers); record(items,"private gateway authenticated /metrics",status,200,{"response":value})
    for system,paths in ROUTES.items():
        for index,path in enumerate(paths):
            event_id=f"gateway-audit-{system}-{index}-{run}"
            body={"safe_test":True,"job_id":f"job-{index}-{run}","message_id":f"message-{index}-{run}","customer_id":"synthetic-customer"}
            if path.endswith("/results"): body.update({"record_id":"record-"+run,"source_url":"http://example.invalid/audit","business_name":"Synthetic Audit","crawl_timestamp":datetime.now(timezone.utc).isoformat()})
            signed=headers(system,event_id,body); status,value=call("POST",path,body,signed)
            record(items,f"{system} route {path} valid signed event",status,202,{"event_id":event_id,"response":value})
            status,value=call("POST",path,body,signed); record(items,f"{system} route {path} replay rejected",status,409,{"event_id":event_id,"response":value})
        path=paths[0]; event_id=f"gateway-negative-{system}-{run}"; body={"safe_test":True,"job_id":"negative-"+run,"message_id":"negative-"+run}
        status,value=call("POST",path,body,headers(system,event_id,body,bad=True)); record(items,f"{system} invalid HMAC rejected",status,401,{"response":value})
        status,value=call("POST",path,body,headers(system,event_id+"-stale",body,int(time.time())-900)); record(items,f"{system} stale timestamp rejected",status,401,{"response":value})
        invalid=headers(system,event_id+"-key",body); invalid["Authorization"]="Bearer invalid-audit-key"
        status,value=call("POST",path,body,invalid); record(items,f"{system} invalid API key rejected",status,401,{"response":value})
    return {"schema_version":"private-gateway-audit.v1","run_id":run,"safe_mode":True,"summary":{"pass":sum(x["status"]=="PASS" for x in items),"fail":sum(x["status"]=="FAIL" for x in items)},"tests":items}


if __name__=="__main__":
    if "--inside" in sys.argv: print(json.dumps(inside(),indent=2,sort_keys=True))
    else:
        result=subprocess.run(["docker","exec","-i",CONTAINER,"python","-","--inside"],input=Path(__file__).read_bytes(),capture_output=True,timeout=90)
        if result.returncode: sys.stderr.buffer.write(result.stderr)
        else: sys.stdout.buffer.write(result.stdout)
        raise SystemExit(result.returncode)
