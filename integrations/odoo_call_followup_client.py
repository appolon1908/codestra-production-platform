"""Reference client for the Codestra Odoo completed-call RPC v1 contract.

This file intentionally contains no credentials. Load the Odoo base URL,
database, login, and API key from the runtime secret store.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import time
import xmlrpc.client
from typing import Any


@dataclass(frozen=True)
class OdooRpcConfig:
    base_url: str
    database: str
    login: str
    api_key: str
    timeout_seconds: float = 8.0
    max_attempts: int = 5


class TimeoutTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection


class OdooCallFollowupClient:
    def __init__(self, config: OdooRpcConfig):
        self.config = config
        transport = TimeoutTransport(config.timeout_seconds)
        self.common = xmlrpc.client.ServerProxy(
            f"{config.base_url.rstrip('/')}/xmlrpc/2/common",
            allow_none=True,
            transport=transport,
        )
        self.models = xmlrpc.client.ServerProxy(
            f"{config.base_url.rstrip('/')}/xmlrpc/2/object",
            allow_none=True,
            transport=transport,
        )
        self.uid = self.common.authenticate(
            config.database,
            config.login,
            config.api_key,
            {},
        )
        if not self.uid:
            raise RuntimeError("Odoo API-key authentication failed")

    def _execute(self, method: str, *args: Any) -> Any:
        return self.models.execute_kw(
            self.config.database,
            self.uid,
            self.config.api_key,
            "codestra.crm.call.followup",
            method,
            list(args),
            {},
        )

    def register_completed_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                result = self._execute("register_completed_call_v1", payload)
                required = {
                    "api_version",
                    "accepted",
                    "followup_id",
                    "event_id",
                    "state",
                    "replayed",
                    "request_fingerprint",
                }
                if not isinstance(result, dict) or not required.issubset(result):
                    raise RuntimeError("Odoo returned an invalid registration response")
                return result
            except (OSError, TimeoutError, xmlrpc.client.ProtocolError) as exc:
                last_error = exc
                if attempt == self.config.max_attempts:
                    break
                delay = min(30.0, 0.5 * (2 ** (attempt - 1)))
                time.sleep(delay + random.uniform(0.0, delay * 0.25))
        raise RuntimeError(
            "Odoo completed-call registration exhausted its retry budget"
        ) from last_error

    def status(self, company_id: int, event_id: str) -> dict[str, Any]:
        return self._execute(
            "get_completed_call_status_v1",
            company_id,
            event_id,
        )
