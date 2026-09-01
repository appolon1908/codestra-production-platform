#!/usr/bin/env python3
import pathlib
import re

path = pathlib.Path("reports/AMBIGUOUS_WORKLOAD_ADOPTION_PLANS_20260901.md")
text = path.read_text()
workloads = [
    "codestra-beyvra-email-api-1",
    "codestra-email-reseller-api-1",
    "codestra-mail-api-mail-api-1",
    "codestra-provisioning-service-provisioning-service-1",
    "codestra-reseller-portal-portal-1",
]
assert all(text.count(f"`{name}`") == 1 for name in workloads)
assert text.count("Local-only files:") == 5
assert text.count("Protected-only files:") == 5
assert text.count("Conflicts:") == 5
assert text.count("Secret-bearing files excluded:") == 5
assert "runtime equivalence unproven" in text
assert "Do not copy the dirty worktree" in text
assert "No dirty worktree was pushed" in text
for value in re.findall(r"`([0-9a-f]+)`", text):
    assert len(value) == 40, f"invalid source identity: {value}"
for forbidden in ("BEGIN PRIVATE KEY", "ghp_", "github_pat_", "password="):
    assert forbidden.lower() not in text.lower()
print("AMBIGUOUS_ADOPTION_PLANS=5/5")
