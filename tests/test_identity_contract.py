from datetime import datetime, timezone

import pytest

from identity.contract import IdentityError, ServiceIdentityContract


NOW = datetime(2026, 8, 14, 18, 0, tzinfo=timezone.utc)


def contract():
    return ServiceIdentityContract(
        issuer="https://auth.codestra.agency/realms/production",
        audience="codestra-middleware",
        client_id="vicidial-event-publisher",
        required_roles=frozenset({"event:publish"}),
        allowed_tenants=frozenset({"tenant-synthetic"}),
    )


def claims(**changes):
    value = {
        "iss": contract().issuer,
        "aud": [contract().audience],
        "azp": contract().client_id,
        "iat": int(NOW.timestamp()) - 10,
        "exp": int(NOW.timestamp()) + 290,
        "jti": "token-1",
        "tenant_id": "tenant-synthetic",
        "realm_access": {"roles": ["event:publish"]},
    }
    value.update(changes)
    return value


def test_valid_service_token() -> None:
    contract().authorize(claims(), tenant_id="tenant-synthetic", signature_verified=True, now=NOW)


@pytest.mark.parametrize("change,signature,error", [
    ({"aud": ["wrong"]}, True, "audience"),
    ({"exp": int(NOW.timestamp()) - 1}, True, "currently valid"),
    ({"nbf": int(NOW.timestamp()) + 60}, True, "not valid yet"),
    ({"tenant_id": "tenant-other"}, True, "tenant binding"),
    ({"realm_access": {"roles": []}}, True, "role"),
    ({}, False, "signature"),
])
def test_fail_closed_token_matrix(change, signature, error) -> None:
    with pytest.raises(IdentityError, match=error):
        contract().authorize(claims(**change), tenant_id="tenant-synthetic", signature_verified=signature, now=NOW)
