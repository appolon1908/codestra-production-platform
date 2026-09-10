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
    def test_resolver_requires_exact_branch_and_commit_type(self) -> None:
        from unittest.mock import patch
        good = {"ref": "refs/heads/release/main", "object": {"type": "commit", "sha": "a" * 40}}
        bad = [{**good, "ref": "refs/heads/other"},
               {**good, "object": {"type": "tag", "sha": "a" * 40}},
               {**good, "object": []}, {**good, "object": None}]
        for payload in bad:
            with self.subTest(payload=payload), patch.object(MODULE, "github_request", return_value=payload):
                with self.assertRaises(RuntimeError):
                    MODULE.resolve_ref("owner/repository", "release/main", "test-only")
        with patch.object(MODULE, "github_request", return_value=good):
            self.assertEqual(MODULE.resolve_ref("owner/repository", "release/main", "test-only"), "a" * 40)

    def test_authenticated_requests_cannot_follow_redirects(self) -> None:
        for target in ["https://attacker.invalid/", "https://api.github.com/other"]:
            with self.assertRaisesRegex(RuntimeError, "redirect rejected"):
                MODULE.NoGitHubRedirect().redirect_request(None, None, 302, "Found", {}, target)

    def test_http_error_does_not_expose_response_body(self) -> None:
        from unittest.mock import patch, MagicMock
        import io
        error = MODULE.urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {}, io.BytesIO(b"private-response-marker"))
        opener = MagicMock()
        opener.open.side_effect = error
        with patch.object(MODULE.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "^GitHub HTTP 403$"):
                MODULE.github_request("/repos/owner/repository", "test-only")

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
