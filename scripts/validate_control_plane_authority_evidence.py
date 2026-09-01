#!/usr/bin/env python3
import pathlib
import re
import subprocess
import base64
import io
import tarfile
import tempfile

REPORT = pathlib.Path("reports/CONTROL_PLANE_SOURCE_AUTHORITY_RECONCILIATION_20260901.md")
text = REPORT.read_text()
runtime = "44d2addf48ae31da6eeb3c3f9ab3fe34d999042c"
protected = "aa3d903648d5f7c4cc10acee93e509a37ac36f76"
runtime_patch = pathlib.Path("reports/CONTROL_PLANE_RUNTIME_44D2_SERVICE_TREE.patch.b64")

required = [
    "CONTROL_PLANE_RUNTIME_ONLY_CHANGES",
    "CONTROL_PLANE_PROTECTED_ONLY_CHANGES",
    "CONTROL_PLANE_CONFLICTS",
    "Disposition C",
    "Production replacement: prohibited",
    "Migration execution: prohibited",
]
for value in required:
    assert value in text, f"missing reconciliation field: {value}"
for value in re.findall(r"`([0-9a-f]{40})`", text):
    assert re.fullmatch(r"[0-9a-f]{40}", value)
assert runtime in text and protected in text
subprocess.run(["git", "cat-file", "-e", f"{runtime}^{{commit}}"], check=True)
assert runtime_patch.is_file() and runtime_patch.stat().st_size > 0

# The checked-in patch is a durable, inspectable reconstruction bundle. Apply
# it to the named protected baseline, then compare every reconstructed file to
# the runtime commit. This remains valid after a squash merge drops PR ancestry.
archive = subprocess.check_output(["git", "archive", protected, "control_plane_service"])
runtime_files = subprocess.check_output(
    ["git", "ls-tree", "-r", "--name-only", runtime, "control_plane_service"], text=True
).splitlines()
with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    decoded_patch = root / "runtime-service-tree.patch"
    decoded_patch.write_bytes(base64.b64decode(b"".join(runtime_patch.read_bytes().split()), validate=True))
    with tarfile.open(fileobj=io.BytesIO(archive)) as value:
        value.extractall(root, filter="data")
    subprocess.run(["git", "apply", str(decoded_patch)], cwd=root, check=True)
    reconstructed = sorted(
        str(value.relative_to(root)) for value in (root / "control_plane_service").rglob("*") if value.is_file()
    )
    assert reconstructed == runtime_files, "runtime service-tree file set mismatch"
    for name in runtime_files:
        assert (root / name).read_bytes() == subprocess.check_output(["git", "show", f"{runtime}:{name}"])

assert subprocess.run(
    ["git", "diff", "--quiet", runtime, protected, "--", "control_plane_service"]
).returncode == 1, "reconciliation must not claim byte-identical service trees"
assert "authorize a production build" not in text.lower()
print("CONTROL_PLANE_RECONCILIATION_EVIDENCE=PASS")
