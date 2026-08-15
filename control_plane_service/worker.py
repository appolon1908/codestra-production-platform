from __future__ import annotations

import json
import os
import time
import urllib.request

from .core import Store
from .providers import submit

MAX_ATTEMPTS = int(os.getenv("CONTROL_PLANE_MAX_ATTEMPTS", "5"))


def store() -> Store:
    return Store(os.getenv("CONTROL_PLANE_DB", "/data/control-plane.db"))


def once() -> int:
    if os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true":
        return 0
    current = store()
    with current.connect() as db:
        rows = db.execute("SELECT e.*,d.target,d.attempts delivery_attempts FROM events e JOIN event_deliveries d ON d.event_id=e.event_id WHERE d.state IN ('queued','retrying') AND d.next_attempt<=? ORDER BY e.created_at LIMIT 50", (time.time(),)).fetchall()
    processed = 0
    for row in rows:
        envelope = json.loads(row["envelope"]); target_name = row["target"]; target = os.getenv("CONTROL_PLANE_" + target_name.upper() + "_URL", "")
        if not target: continue
        try:
            req = urllib.request.Request(target, row["envelope"].encode(), {"Content-Type": "application/json", "X-Correlation-Id": row["correlation_id"]}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status >= 300: raise RuntimeError("downstream_status")
            with current.connect() as db:
                db.execute("UPDATE event_deliveries SET state='delivered',last_error=NULL WHERE event_id=? AND target=?", (row["event_id"],target_name))
                pending=db.execute("SELECT count(*) FROM event_deliveries WHERE event_id=? AND state!='delivered'",(row["event_id"],)).fetchone()[0]
                if pending==0: db.execute("UPDATE events SET state='delivered',last_error=NULL WHERE event_id=?",(row["event_id"],))
        except Exception as exc:
            attempts = row["delivery_attempts"] + 1; state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"; delay = min(300, 2 ** attempts)
            with current.connect() as db:
                db.execute("UPDATE event_deliveries SET state=?,attempts=?,next_attempt=?,last_error=? WHERE event_id=? AND target=?",(state,attempts,time.time()+delay,type(exc).__name__,row["event_id"],target_name))
                db.execute("UPDATE events SET state=?,attempts=max(attempts,?),next_attempt=?,last_error=? WHERE event_id=?",(state,attempts,time.time()+delay,type(exc).__name__,row["event_id"]))
        processed += 1
    return processed


def dispatch_messages() -> int:
    if os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true":
        return 0
    current = store(); processed = 0
    with current.connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM messages WHERE status='queued' ORDER BY created_at LIMIT 50")]
    for message in rows:
        if not current.circuit_allows(message["provider"], int(os.getenv("CONTROL_PLANE_CIRCUIT_COOLDOWN", "30"))):
            continue
        try:
            result = submit(message)
            current.transition_message(message["message_id"], message["tenant_id"], result.status, result.raw_status, provider_message_id=result.provider_message_id)
            current.circuit_result(message["provider"], True)
        except Exception as exc:
            current.circuit_result(message["provider"], False, int(os.getenv("CONTROL_PLANE_CIRCUIT_THRESHOLD", "3")))
            with current.connect() as db:
                row=db.execute("SELECT retry_count FROM messages WHERE message_id=?",(message["message_id"],)).fetchone(); attempts=row["retry_count"]+1
                db.execute("UPDATE messages SET status=?,retry_count=?,provider_error_code=? WHERE message_id=?",("failed" if attempts>=MAX_ATTEMPTS else "queued",attempts,type(exc).__name__,message["message_id"]))
        processed += 1
    return processed


def main() -> None:
    while True:
        once(); dispatch_messages(); time.sleep(1)


if __name__ == "__main__":
    main()
