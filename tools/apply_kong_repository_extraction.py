#!/usr/bin/env python3
"""One-time source refactor: replace local Kong implementation with a pinned repo lock."""

from __future__ import annotations

import json
import re
import shutil
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KONG_REPOSITORY = "appolon1908-hue/Kong"
KONG_COMMIT = "007055bbd05b9cd1c7cc33d3810ec17a3ec9fbba"
SOURCE_PLATFORM_SHA = "f3a16308194378a7b1580e04943dc98d64619077"
SOURCE_ROUTE_SHA = "b340023f5e74e1f9154fc97590c9b6a48caa8b99"


def remove_path(relative: str) -> None:
    path = ROOT / relative
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def replace_required(path: Path, old: str, new: str) -> None:
    value = path.read_text(encoding="utf-8")
    if old not in value:
        raise SystemExit(f"required source block not found in {path}")
    path.write_text(value.replace(old, new), encoding="utf-8")


def write_lock() -> None:
    lock = {
        "schema": "codestra.platform.external-source-lock.v1",
        "component": "kong-gateway",
        "repository": KONG_REPOSITORY,
        "commit": KONG_COMMIT,
        "manifest_path": "MIGRATION_MANIFEST.json",
        "manifest_schema": "codestra.kong.repository-migration.v1",
        "source_platform_sha": SOURCE_PLATFORM_SHA,
        "source_route_pr": 130,
        "source_route_sha": SOURCE_ROUTE_SHA,
        "required_paths": [
            "deploy/kong/control-plane.yml",
            "deploy/kong/scope-policy.lua",
            "deploy/kong-production-standby/compose.standby.yaml",
            "operations/kong-database/README.md",
            "scripts/reconcile_kong_canonical_routes.py",
            "tests/test_kong_route_authority_hardening.py",
        ],
        "public_routes": [
            {
                "service": "codestra-control-plane",
                "route": "control-plane-control",
                "methods": ["PATCH", "POST"],
                "paths": ["/api/v1/control"],
                "hosts": ["api.codestra.co"],
            },
            {
                "service": "codestra-control-plane",
                "route": "communication-message-read",
                "methods": ["GET"],
                "paths": ["/api/v1/messages"],
                "hosts": ["api.codestra.co"],
            },
            {
                "service": "codestra-control-plane",
                "route": "control-plane-events",
                "methods": ["POST"],
                "paths": ["/api/v1/events"],
                "hosts": ["api.codestra.co"],
            },
            {
                "service": "codestra-control-plane",
                "route": "control-plane-results",
                "methods": ["POST"],
                "paths": ["/api/v1/results"],
                "hosts": ["api.codestra.co"],
            },
            {
                "service": "codestra-control-plane",
                "route": "control-plane-reconciliation",
                "methods": ["GET", "POST"],
                "paths": ["/api/v1/reconciliation"],
                "hosts": ["api.codestra.co"],
            },
            {
                "service": "codestra-control-plane",
                "route": "control-plane-health",
                "methods": ["GET"],
                "paths": ["/api/v1/health"],
                "hosts": ["api.codestra.co"],
            },
            {
                "service": "codestra-control-plane",
                "route": "control-plane-system-admin",
                "methods": ["GET"],
                "paths": ["/v1/admin/system"],
                "hosts": ["api.codestra.co"],
            },
        ],
        "security_contracts": {
            "system_admin_required_scope": "platform.admin",
            "authenticated_role_headers": ["platform_admin", "tenant_admin"],
        },
        "local_implementation_paths_must_be_absent": [
            "deploy/kong",
            "deploy/kong-production-standby",
            "operations/kong-database",
            "config/kong-callback-routes.json",
            "config/kong-campaign-automation-routes.json",
            "config/kong-canonical-middleware-routes.json",
        ],
        "production_state_changed": False,
    }
    (ROOT / "config/kong-source.lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_verifier() -> None:
    source = textwrap.dedent(
        '''\
        #!/usr/bin/env python3
        """Verify the pinned standalone Kong source authority."""

        from __future__ import annotations

        import argparse
        import json
        import re
        import urllib.request
        from pathlib import Path
        from typing import Any

        import yaml

        ROOT = Path(__file__).resolve().parents[1]
        LOCK_PATH = ROOT / "config/kong-source.lock.json"
        SHA40 = re.compile(r"^[0-9a-f]{40}$")


        def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
            value = json.loads(path.read_text(encoding="utf-8"))
            assert value["schema"] == "codestra.platform.external-source-lock.v1"
            assert value["component"] == "kong-gateway"
            assert value["repository"] == "appolon1908-hue/Kong"
            assert SHA40.fullmatch(value["commit"])
            assert SHA40.fullmatch(value["source_platform_sha"])
            assert SHA40.fullmatch(value["source_route_sha"])
            assert value["production_state_changed"] is False
            return value


        def verify_local_absence(lock: dict[str, Any], root: Path = ROOT) -> None:
            unexpected = [
                relative
                for relative in lock["local_implementation_paths_must_be_absent"]
                if (root / relative).exists()
            ]
            if unexpected:
                raise SystemExit(
                    "duplicated Kong source remains in platform: " + ",".join(unexpected)
                )


        def fetch_text(url: str) -> str:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "codestra-platform-kong-source-lock/1"},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8")


        def normalized_routes(document: dict[str, Any]) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for service in document.get("services", []):
                for route in service.get("routes", []):
                    rows.append(
                        {
                            "service": service.get("name"),
                            "route": route.get("name"),
                            "methods": sorted(route.get("methods", ["ANY"])),
                            "paths": sorted(route.get("paths", [])),
                            "hosts": sorted(route.get("hosts", [])),
                        }
                    )
            return sorted(rows, key=lambda row: (row["service"], row["route"]))


        def verify_online(lock: dict[str, Any]) -> None:
            base = (
                f"https://raw.githubusercontent.com/"
                f"{lock['repository']}/{lock['commit']}"
            )
            manifest = json.loads(fetch_text(f"{base}/{lock['manifest_path']}"))
            assert manifest["schema"] == lock["manifest_schema"]
            assert manifest["target_repository"] == lock["repository"]
            assert manifest["source_protected_sha"] == lock["source_platform_sha"]
            assert manifest["source_route_sha"] == lock["source_route_sha"]
            available = {row["path"] for row in manifest["files"]}
            missing = sorted(set(lock["required_paths"]) - available)
            if missing:
                raise SystemExit(
                    "standalone Kong source missing required paths: " + ",".join(missing)
                )

            kong = yaml.safe_load(fetch_text(f"{base}/deploy/kong/control-plane.yml"))
            expected = sorted(
                lock["public_routes"], key=lambda row: (row["service"], row["route"])
            )
            if normalized_routes(kong) != expected:
                raise SystemExit(
                    "standalone Kong public route contract differs from platform lock"
                )

            scope_policy = fetch_text(f"{base}/deploy/kong/scope-policy.lua")
            security = lock["security_contracts"]
            assert security["system_admin_required_scope"] in scope_policy
            for role in security["authenticated_role_headers"]:
                assert (
                    f'set_header("X-Authenticated-Role", "{role}")'
                    in scope_policy
                )


        def main() -> None:
            parser = argparse.ArgumentParser()
            parser.add_argument("--online", action="store_true")
            args = parser.parse_args()
            lock = load_lock()
            verify_local_absence(lock)
            if args.online:
                verify_online(lock)
            print(
                f"KONG_SOURCE_AUTHORITY=PASS REPOSITORY={lock['repository']} "
                f"COMMIT={lock['commit']} ONLINE={'YES' if args.online else 'NO'}"
            )


        if __name__ == "__main__":
            main()
        '''
    )
    path = ROOT / "tools/verify_kong_source_lock.py"
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def patch_architecture_validator() -> None:
    path = ROOT / "tools/check_integration_architecture.py"
    old = textwrap.dedent(
        '''\
            kong_path = root / "deploy/kong/control-plane.yml"
            if kong_path.exists():
                kong = load_yaml(kong_path)
                for service in kong.get("services", []):
                    for route in service.get("routes", []):
                        for path in route.get("paths", []):
                            for method in route.get("methods", ["ANY"]):
                                discovered.add((str(method).upper(), str(path), str(kong_path.relative_to(root))))
        '''
    )
    new = textwrap.dedent(
        '''\
            kong_lock_path = root / "config/kong-source.lock.json"
            if kong_lock_path.exists():
                kong_lock = json.loads(kong_lock_path.read_text(encoding="utf-8"))
                for route in kong_lock.get("public_routes", []):
                    for path in route.get("paths", []):
                        for method in route.get("methods", ["ANY"]):
                            discovered.add((str(method).upper(), str(path), str(kong_lock_path.relative_to(root))))
        '''
    )
    replace_required(path, old, new)


def patch_workflows() -> None:
    pattern = re.compile(
        r"\n\s*python -m pytest -q \\\n"
        r"\s*deploy/kong-production-standby/auth-middleware/test_token_validation\.py"
    )
    for relative in (
        ".github/workflows/platform-source-gate.yml",
        ".github/workflows/protected-release.yml",
    ):
        path = ROOT / relative
        value = path.read_text(encoding="utf-8")
        value, count = pattern.subn(
            "\n          python tools/verify_kong_source_lock.py --online", value
        )
        if count != 1:
            raise SystemExit(f"expected one legacy Kong test invocation in {relative}")
        path.write_text(value, encoding="utf-8")


def rewrite_tests() -> None:
    remove_path("tests/test_kong_control_plane.py")
    platform_test = textwrap.dedent(
        '''\
        from pathlib import Path
        import hashlib

        from control_plane_service.server import Handler

        ROOT = Path(__file__).resolve().parents[1]


        def test_trusted_proxy_headers_also_require_gateway_secret(monkeypatch, tmp_path):
            secret = "synthetic-gateway-secret"
            verifier = tmp_path / "verifier"
            verifier.write_text(hashlib.sha256(secret.encode()).hexdigest())
            monkeypatch.setenv("CONTROL_PLANE_TRUSTED_PROXY_CIDRS", "10.0.0.2/32")
            monkeypatch.setenv("KONG_GATEWAY_SHARED_SECRET_SHA256_FILE", str(verifier))
            handler = Handler.__new__(Handler)
            handler.client_address = ("10.0.0.2", 1234)
            handler.headers = {
                "X-Authenticated-Client": "n8n",
                "X-Authenticated-Tenant": "COD",
            }
            denied = []
            handler.send_json = lambda code, value: denied.append((code, value))
            assert handler.auth_operator({"tenant_admin"}) is None
            assert denied[0][0] == 403
            handler.headers["X-Codestra-Gateway-Secret"] = secret
            assert handler.auth_operator({"tenant_admin"}) == (
                "n8n",
                "tenant_admin",
                "COD",
            )
            assert handler.auth_operator({"platform_admin"}) is None
            handler.headers["X-Authenticated-Role"] = "platform_admin"
            assert handler.auth_operator({"platform_admin"}) == (
                "n8n",
                "platform_admin",
                "COD",
            )


        def test_postgres_base_schema_precedes_runtime_and_mailbox_migrations():
            migration = (ROOT / "migrations/control_plane/000_runtime_store.sql").read_text()
            for table in (
                "events",
                "messages",
                "integrations",
                "circuits",
                "preferences",
                "suppressions",
            ):
                assert f"public.{table}" in migration


        def test_complete_granular_communication_scope_catalog_is_documented():
            matrix = (ROOT / "reports/COMMUNICATION_OAUTH_SCOPE_MATRIX.csv").read_text()
            required = {
                "communications.message.create",
                "communications.message.read",
                "communications.message.dispatch",
                "communications.message.events.read",
                "communications.sms.create",
                "communications.sms.dispatch",
                "communications.sms.events.read",
                "communications.email.create",
                "communications.email.dispatch",
                "communications.email.events.read",
                "communications.result.write",
                "communications.reconciliation.read",
                "communications.reconciliation.execute",
                "communications.admin",
            }
            assert not (
                required - set(matrix.replace(",", " ").replace('"', " ").split())
            )


        def test_control_plane_implements_business_aliases_without_provider_duplication():
            source = (ROOT / "control_plane_service/server.py").read_text()
            for path in (
                "/api/v1/control/messages",
                "/api/v1/messages/",
                "/api/v1/results/messages/",
            ):
                assert path in source
            assert "STORE.create_message(value)" in source


        def test_signed_provider_event_ids_are_single_use_nonces():
            source = (ROOT / "control_plane_service/server.py").read_text()
            assert 'source in {"odoo", "telnexa", "klyrow"}' in source
            assert '"replayed_event_id"' in source
        '''
    )
    (ROOT / "tests/test_control_plane_platform_contracts.py").write_text(
        platform_test, encoding="utf-8"
    )

    health = ROOT / "tests/test_system_health_contract.py"
    old = textwrap.dedent(
        '''\
        def test_kong_system_route_requires_platform_admin_scope_and_role_header():
            kong = (ROOT / "deploy/kong/control-plane.yml").read_text()
            assert "paths: [/v1/admin/system]" in kong
            assert 'required = "platform.admin"' in kong
            assert 'set_header("X-Authenticated-Role", "platform_admin")' in kong
            assert 'set_header("X-Authenticated-Role", "tenant_admin")' in kong
        '''
    )
    new = textwrap.dedent(
        '''\
        def test_kong_system_route_contract_is_pinned_to_standalone_authority():
            import json

            lock = json.loads((ROOT / "config/kong-source.lock.json").read_text())
            route = next(
                row
                for row in lock["public_routes"]
                if row["route"] == "control-plane-system-admin"
            )
            assert route["methods"] == ["GET"]
            assert route["paths"] == ["/v1/admin/system"]
            assert route["hosts"] == ["api.codestra.co"]
            assert (
                lock["security_contracts"]["system_admin_required_scope"]
                == "platform.admin"
            )
            assert lock["security_contracts"]["authenticated_role_headers"] == [
                "platform_admin",
                "tenant_admin",
            ]
        '''
    )
    replace_required(health, old, new)

    lock_tests = textwrap.dedent(
        '''\
        import json
        from pathlib import Path

        from tools.verify_kong_source_lock import load_lock, verify_local_absence

        ROOT = Path(__file__).resolve().parents[1]


        def test_kong_source_lock_is_exact_and_fail_closed():
            lock = load_lock()
            assert lock["repository"] == "appolon1908-hue/Kong"
            assert lock["commit"] == "007055bbd05b9cd1c7cc33d3810ec17a3ec9fbba"
            assert lock["production_state_changed"] is False
            verify_local_absence(lock)


        def test_platform_keeps_only_cross_system_route_summary():
            lock = json.loads((ROOT / "config/kong-source.lock.json").read_text())
            assert len(lock["public_routes"]) == 7
            assert all(
                row["hosts"] == ["api.codestra.co"]
                for row in lock["public_routes"]
            )
            assert not any(
                (ROOT / relative).exists()
                for relative in lock["local_implementation_paths_must_be_absent"]
            )
        '''
    )
    (ROOT / "tests/test_kong_source_lock.py").write_text(
        lock_tests, encoding="utf-8"
    )


def write_docs() -> None:
    directory = ROOT / "docs/architecture"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "kong-source-authority.md").write_text(
        textwrap.dedent(
            '''\
            # Kong source authority

            Kong implementation and database operations are owned by
            `appolon1908-hue/Kong` at the immutable commit recorded in
            `config/kong-source.lock.json`.

            The platform repository retains only the cross-system dependency contract,
            release lock, and verification tooling. It no longer owns Kong route manifests,
            plugin configuration, standby implementation, database roles, backup/PITR/HA
            scripts, or Kong-specific tests.

            This source move does not change the production topology:

            ```text
            public client -> host Caddy -> Docker upstream-gateway -> private Kong -> private services
            ```

            Updating the lock requires a reviewed Kong commit, passing standalone Kong CI,
            an updated platform PR, and exact-head validation. Applying a Kong change to the
            live Admin API remains a separate maintenance-window operation.
            '''
        ),
        encoding="utf-8",
    )
    architecture = ROOT / "ARCHITECTURE.md"
    if architecture.exists():
        value = architecture.read_text(encoding="utf-8")
        if "## Kong source authority" not in value:
            value += textwrap.dedent(
                '''

                ## Kong source authority

                Kong implementation is maintained in `appolon1908-hue/Kong`. This
                repository pins the approved commit in `config/kong-source.lock.json`
                and retains only cross-system integration metadata. See
                `docs/architecture/kong-source-authority.md`.
                '''
            )
            architecture.write_text(value, encoding="utf-8")


def main() -> None:
    for relative in (
        "deploy/kong",
        "deploy/kong-production-standby",
        "operations/kong-database",
        "config/kong-callback-routes.json",
        "config/kong-campaign-automation-routes.json",
        "config/kong-canonical-middleware-routes.json",
        "operations/runbooks/kong-production-activation.md",
        "operations/runbooks/kong-production-rollback.md",
        "scripts/apply_kong_standby.py",
        "scripts/export_kong_public_route_contracts.py",
        "scripts/reconcile_kong_callback_routes.py",
        "scripts/reconcile_kong_campaign_automation.py",
        "scripts/reconcile_kong_canonical_routes.py",
        "scripts/rollback_kong_standby.py",
        "scripts/run_kong_standby_acceptance.py",
        "scripts/validate_kong_production_standby.py",
        "tests/test_kong_change_authority.py",
        "tests/test_kong_database_operations.py",
        "tests/test_kong_canonical_route_contract.py",
        "tests/test_kong_route_authority_hardening.py",
    ):
        remove_path(relative)

    write_lock()
    write_verifier()
    patch_architecture_validator()

    pytest_ini = ROOT / "pytest.ini"
    pytest_ini.write_text(
        pytest_ini.read_text(encoding="utf-8").replace(
            "    deploy/kong-production-standby/auth-middleware\n", ""
        ),
        encoding="utf-8",
    )

    patch_workflows()
    rewrite_tests()
    write_docs()

    # This helper is intentionally one-time source scaffolding.
    Path(__file__).unlink()
    print("KONG_PLATFORM_EXTRACTION_APPLIED=YES")


if __name__ == "__main__":
    main()
