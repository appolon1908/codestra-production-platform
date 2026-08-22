from __future__ import annotations

from .core import ControlPlaneError, Store


def select_channel(store: Store, tenant: str, customer: str, policy: dict[str, object]) -> str:
    """Return only an explicitly configured, permitted channel; never infer fallback."""
    preferred = str(policy.get("preferred_channel", ""))
    if preferred not in {"sms", "email"}:
        raise ControlPlaneError("routing_policy_required")
    classification = str(policy.get("classification", "marketing"))
    if classification == "marketing" and not store.preference_allows(tenant, customer, preferred):
        fallback = str(policy.get("fallback_channel", ""))
        if not policy.get("fallback_enabled") or fallback not in {"sms", "email"} or not store.preference_allows(tenant, customer, fallback):
            raise ControlPlaneError("no_permitted_channel")
        return fallback
    return preferred
