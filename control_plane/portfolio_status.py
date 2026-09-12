"""Secret-free portfolio readiness API contract.

The module is deliberately framework-neutral so HTTP, CLI, and job callers
share the same validation and fail-closed semantics.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

REQUIRED_GATES = ("source_locked", "image_pinned", "checks_green", "approval_recorded")
ReadinessState = Literal["ready", "blocked"]


class ReadinessPayload(TypedDict):
    schema_version: str
    status: ReadinessState
    gates: dict[str, bool]
    failed_gates: list[str]
    gate_count: int
    external_effects: Literal["disabled"]
    as_of: str


@dataclass(frozen=True)
class GateSnapshot:
    """Validated gate values used to build a readiness response."""

    values: dict[str, bool]

    @classmethod
    def from_mapping(cls, gates: Mapping[str, bool]) -> "GateSnapshot":
        if not isinstance(gates, Mapping):
            raise TypeError("gates must be a mapping")
        invalid = [name for name in REQUIRED_GATES if name in gates and not isinstance(gates[name], bool)]
        if invalid:
            raise ValueError(f"gate values must be booleans: {', '.join(invalid)}")
        return cls({name: gates.get(name, False) for name in REQUIRED_GATES})

    @property
    def failed(self) -> list[str]:
        return [name for name in REQUIRED_GATES if not self.values[name]]


def _utc_timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if not isinstance(current, datetime):
        raise TypeError("as_of must be a datetime")
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def portfolio_status(
    gates: Mapping[str, bool], *, as_of: datetime | None = None
) -> ReadinessPayload:
    """Return a deterministic, non-secret readiness payload for control-plane clients."""
    snapshot = GateSnapshot.from_mapping(gates)
    failed = snapshot.failed
    return {
        "schema_version": "portfolio.readiness.v1",
        "status": "ready" if not failed else "blocked",
        "gates": snapshot.values,
        "failed_gates": failed,
        "gate_count": len(REQUIRED_GATES),
        "external_effects": "disabled",
        "as_of": _utc_timestamp(as_of),
    }
