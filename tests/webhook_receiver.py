from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        print(
            json.dumps(
                {
                    "status": payload.get("status"),
                    "alerts": [
                        {
                            "status": alert.get("status"),
                            "alertname": alert.get("labels", {}).get("alertname"),
                        }
                        for alert in payload.get("alerts", [])
                    ],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 19093), Receiver)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
