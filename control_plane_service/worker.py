from __future__ import annotations

import json
import os
import time
import urllib.request

from .core import Store

MAX_ATTEMPTS = int(os.getenv("CONTROL_PLANE_MAX_ATTEMPTS", "5"))


def store() -> Store:
    return Store(os.getenv("CONTROL_PLANE_DB", "/data/control-plane.db"))


def once() -> int:
    if os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true":
        return 0
    current = store()
    with current.connect() as db:
        rows = db.execute("SELECT * FROM events WHERE state IN ('queued','retrying') AND next_attempt<=? ORDER BY created_at LIMIT 50", (time.time(),)).fetchall()
    processed = 0
    for row in rows:
        envelope = json.loads(row["envelope"]); target_name = "odoo" if row["source"] != "odoo" else "n8n"; target = os.getenv("CONTROL_PLANE_" + target_name.upper() + "_URL", "")
        if not target: continue
        try:
            req = urllib.request.Request(target, row["envelope"].encode(), {"Content-Type": "application/json", "X-Correlation-Id": row["correlation_id"]}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status >= 300: raise RuntimeError("downstream_status")
            with current.connect() as db: db.execute("UPDATE events SET state='delivered',last_error=NULL WHERE event_id=?", (row["event_id"],))
        except Exception as exc:
            attempts = row["attempts"] + 1; state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"; delay = min(300, 2 ** attempts)
            with current.connect() as db: db.execute("UPDATE events SET state=?,attempts=?,next_attempt=?,last_error=? WHERE event_id=?", (state, attempts, time.time() + delay, type(exc).__name__, row["event_id"]))
        processed += 1
    return processed


def main() -> None:
    while True:
        once(); time.sleep(1)


if __name__ == "__main__":
    main()
