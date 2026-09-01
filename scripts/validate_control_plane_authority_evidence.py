#!/usr/bin/env python3
import pathlib
import re
import subprocess

REPORT = pathlib.Path("reports/CONTROL_PLANE_SOURCE_AUTHORITY_RECONCILIATION_20260901.md")
text = REPORT.read_text()
runtime = "44d2addf48ae31da6eeb3c3f9ab3fe34d999042c"
protected = "aa3d903648d5f7c4cc10acee93e509a37ac36f76"

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
subprocess.run(["git", "diff", "--quiet", runtime, "HEAD", "--", "control_plane"], check=True)
assert "authorize a production build" not in text.lower()
print("CONTROL_PLANE_RECONCILIATION_EVIDENCE=PASS")
