"""Shared HTTP transport and authentication primitives for the control plane."""

from .auth import OperatorIdentity, OperatorResolution, resolve_operator
from .http import (
    is_form_preflight_allowed,
    read_request_body,
    write_form_preflight,
    write_json_response,
)

__all__ = [
    "OperatorIdentity",
    "OperatorResolution",
    "is_form_preflight_allowed",
    "read_request_body",
    "resolve_operator",
    "write_form_preflight",
    "write_json_response",
]
