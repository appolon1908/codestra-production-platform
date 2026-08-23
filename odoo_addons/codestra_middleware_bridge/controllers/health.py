from __future__ import annotations

import os

from odoo import http, tools
from odoo.http import request


class CodestraHealth(http.Controller):
    @http.route(
        "/codestra/healthz",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def healthz(self):
        return request.make_json_response({"status": "alive", "service": "odoo"})

    @http.route(
        "/codestra/readyz",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def readyz(self):
        try:
            request.env.cr.execute("SELECT 1")
            filestore = tools.config.filestore(request.db)
            if not os.path.isdir(filestore) or not os.access(filestore, os.R_OK):
                raise OSError("filestore unavailable")
        except Exception:
            return request.make_json_response(
                {"status": "not_ready", "service": "odoo"}, status=503
            )
        return request.make_json_response(
            {"status": "ready", "service": "odoo", "database": "ready", "filestore": "ready"}
        )

    @http.route(
        "/codestra/version",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def version(self):
        module = request.env["ir.module.module"].sudo().search(
            [("name", "=", "codestra_middleware_bridge")], limit=1
        )
        return request.make_json_response(
            {
                "service": "odoo",
                "module_version": module.latest_version or "unknown",
                "source_sha": os.getenv("SOURCE_SHA", "unknown"),
                "release_id": os.getenv("RELEASE_ID", "unknown"),
            }
        )
