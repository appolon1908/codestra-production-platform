#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_production_source_lock_remote.py"
SPEC = importlib.util.spec_from_file_location("source_audit", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SourceLockRemoteAuditTests(unittest.TestCase):
    def test_extracts_repository_branch_and_sha(self) -> None:
        document = {
            "authority": {
                "repository": "owner/repository",
                "branch": "production",
                "source_sha": "1" * 40,
            }
        }
        records = MODULE.extract_authorities(document)
        self.assertEqual(
            records,
            [
                {
                    "path": "$.authority",
                    "repository": "owner/repository",
                    "branch": "production",
                    "recorded_sha": "1" * 40,
                }
            ],
        )

    def test_normalizes_full_head_ref(self) -> None:
        self.assertEqual(MODULE.normalize_ref("refs/heads/release/production-activation"), "release/production-activation")

    def test_deduplicates_identical_authority(self) -> None:
        authority = {
            "repository": "owner/repository",
            "ref": "refs/heads/main",
            "commit_sha": "2" * 40,
        }
        records = MODULE.extract_authorities({"one": authority, "two": authority})
        self.assertEqual(len(records), 1)

    def test_ignores_non_repository_strings(self) -> None:
        document = {
            "service": {
                "repository": "UNKNOWN",
                "branch": "main",
                "sha": "0" * 40,
            },
            "note": "owner/repository",
        }
        self.assertEqual(MODULE.extract_authorities(document), [])

    def test_branch_without_sha_is_still_audited_as_mismatch_candidate(self) -> None:
        document = {
            "service": {
                "repository": "owner/repository",
                "branch": "main",
                "status": "PENDING",
            }
        }
        records = MODULE.extract_authorities(document)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["recorded_sha"], "")


if __name__ == "__main__":
    unittest.main()
