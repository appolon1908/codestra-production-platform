"""Offline review; never connect, execute a payload, or access production secrets.

Usage: python3.11 validate_review.py /path/to/reviewed/core
Requires existing PyYAML. Uses the real Policy loader and extracted upstream
factory ASTs with a filesystem tripwire before any filesystem operation.
This is partial validation, explicitly NOT live enforcement certification.
"""
import ast
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

core = Path(sys.argv[1]).resolve()
expected = "d6b33822b61e7fccf39547d5cce8add8bc7021f9"
assert subprocess.check_output(
    ["git", "-C", str(core), "rev-parse", "HEAD"], text=True
).strip() == expected
assert not subprocess.check_output(
    ["git", "-C", str(core), "status", "--porcelain"], text=True
).strip(), "Reviewed source must be clean"
sys.dont_write_bytecode = True
sys.path.insert(0, str(core / "src"))
from sentinelx_core.policy import Policy

policy = Policy.from_file(Path(__file__).with_name("config.yaml.candidate"))
assert not policy.allowed_commands and not policy.services
assert not policy.trusted_fetch_hosts
assert policy.file_ops_max_read_bytes == 8192
for path in ("/proc/loadavg", "/proc/meminfo", "/proc/uptime"):
    assert policy.resolve_path(path) == Path(path).resolve()
    assert policy.resolve_path(path, need_write=True) is None
for path in (
    "/etc/sentinelx/identity.json", "/etc/sentinelx/config.yaml",
    "/root/.ssh/id_ed25519", "/etc/shadow", "/etc/asterisk",
    "/var/lib/mysql", "/var/spool/asterisk/monitor", "/var/backups",
    "/proc/loadavg/../../etc/shadow",
):
    assert policy.resolve_path(path) is None
    assert policy.resolve_path(path, need_write=True) is None
for command in ("uptime", "bash -c true", "sudo true", "cat /etc/shadow"):
    assert not policy.is_command_allowed(command)
for service in ("asterisk", "mariadb", "sentinelx-cloud-core"):
    for action in ("start", "stop", "restart", "reload"):
        assert not policy.is_service_action_allowed(service, action)

class ReachedFilesystem(Exception):
    pass

class FilesystemTripwire:
    def mkdir(self, *args, **kwargs):
        raise ReachedFilesystem("blocked by review harness before filesystem access")

class HandlerError(Exception):
    pass

async def probe(filename, factory_name, payload):
    source = core / "src/sentinelx_core/handlers" / filename
    tree = ast.parse(source.read_text())
    factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == factory_name)
    module = ast.Module(body=[factory], type_ignores=[])
    namespace = dict(Policy=Policy, Path=Path, Any=Any,
                     HandlerError=HandlerError, ALLOWED_INTERPRETERS=("bash", "python3"),
                     TIMEOUT_MIN=1, TIMEOUT_MAX=600, BACKGROUND_TIMEOUT_MAX=86400)
    exec(compile(module, str(source), "exec"), namespace)
    handler = namespace[factory_name](policy, FilesystemTripwire())
    try:
        await handler(payload)
    except ReachedFilesystem:
        return "REACHES_FILESYSTEM_WITHOUT_POLICY_REJECTION"
    raise AssertionError("Upstream behavior changed; re-review required")

async def main():
    results = {
        "schema_and_policy_queries": "PASS_OFFLINE_ONLY",
        "script_run": await probe("script.py", "make_script_run_handler", {
            "interpreter": "bash", "content": "true", "timeout": 1,
        }),
        "upload_file": await probe("upload.py", "make_upload_file_handler", {
            "target_path": "review-only.txt", "content_base64": "eA==",
        }),
        "payloads_executed": False,
        "handler_filesystem_operations_performed": False,
        "live_policy_verified": False,
        "installation_ready": False,
    }
    print(json.dumps(results, indent=2))

asyncio.run(main())
