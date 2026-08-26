#!/usr/bin/env python3
from __future__ import annotations

import sys
import urllib.error
import urllib.request


URLS = (
    "http://127.0.0.1:8069/web/health",
    "http://127.0.0.1:8069/web/login",
)


def main() -> int:
    for url in URLS:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "codestra-odoo-healthcheck/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if 200 <= int(response.status) < 400:
                    return 0
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return 1


if __name__ == "__main__":
    sys.exit(main())
