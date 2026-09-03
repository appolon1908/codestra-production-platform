"""Codestra middleware/n8n integration control plane.

The package registers additive event namespaces that are owned by platform
extensions but validated by :mod:`control_plane_service.core`.
"""

from . import core as _core


_ODOO_CALL_FOLLOWUP_PREFIX = "call_followup."
if _ODOO_CALL_FOLLOWUP_PREFIX not in _core.EVENT_PREFIXES["odoo"]:
    _core.EVENT_PREFIXES["odoo"] = (
        *_core.EVENT_PREFIXES["odoo"],
        _ODOO_CALL_FOLLOWUP_PREFIX,
    )
