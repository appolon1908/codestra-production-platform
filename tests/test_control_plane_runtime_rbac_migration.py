from pathlib import Path


def test_control_plane_application_receives_bounded_runtime_role() -> None:
    sql = Path("migrations/control_plane/002_runtime_rbac.sql").read_text().upper()

    assert "ROLNAME='CONTROL_PLANE_APP'" in sql
    assert "GRANT CODESTRA_CONTROL_PLANE_RUNTIME TO CONTROL_PLANE_APP" in sql
    assert "GRANT CODESTRA_CONTROL_PLANE_OWNER TO CONTROL_PLANE_APP" not in sql
    assert "ALTER ROLE CONTROL_PLANE_APP" not in sql
