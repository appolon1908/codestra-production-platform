"""Offline tests: no host changes, Docker calls, BPF loads, or network."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "diagnose_seccomp_runtime.py"
SPEC = importlib.util.spec_from_file_location("seccomp_diagnostics", SOURCE)
diag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diag)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def evidence(self, data):
        path = self.root / "failure.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_errno_524_does_not_prove_exhaustion(self):
        result = diag.classify_error("error loading seccomp filter: errno 524: unknown")
        self.assertEqual(result["classification"], "SECCOMP_FILTER_INSTALLATION_ERRNO_524_REPORTED")
        self.assertEqual(result["bpf_jit_exhaustion"], "NOT_ESTABLISHED")
        self.assertEqual(result["kernel_runtime_incompatibility"], "NOT_ESTABLISHED")

    def test_unrelated_524_is_not_classified_as_seccomp(self):
        self.assertEqual(diag.classify_error("HTTP 524 timeout")["classification"], "NOT_CLASSIFIED")

    def test_unknown_cause_stays_unknown(self):
        self.assertEqual(diag.classify_error("")["bpf_jit_exhaustion"], "NOT_ESTABLISHED")

    def test_5240_is_not_524(self):
        self.assertFalse(diag.classify_error("seccomp filter errno 5240")["errno_524_reported"])

    def test_hashed_evidence_preserves_file_and_excludes_secrets(self):
        path = self.evidence({"error": "seccomp filter errno 524", "password": "sensitive-sentinel"})
        original = path.read_bytes()
        report = diag.inspect_evidence(path)
        self.assertEqual(report["sha256"], hashlib.sha256(original).hexdigest())
        self.assertNotIn("sensitive-sentinel", json.dumps(report))
        self.assertEqual(path.read_bytes(), original)

    def test_malformed_json_is_not_accepted(self):
        path = self.root / "bad.json"
        path.write_text("not json")
        self.assertEqual(diag.inspect_evidence(path)["status"], "INVALID_JSON")

    def test_non_object_evidence_is_not_accepted(self):
        self.assertEqual(diag.inspect_evidence(self.evidence([]))["status"], "INVALID_JSON_OBJECT")

    def test_missing_evidence_is_unavailable(self):
        self.assertEqual(diag.inspect_evidence(self.root / "missing")["status"], "UNAVAILABLE")

    def test_symlink_evidence_is_not_followed(self):
        target = self.evidence({"secret": "sentinel"})
        link = self.root / "link"
        link.symlink_to(target)
        self.assertEqual(diag.inspect_evidence(link)["status"], "UNAVAILABLE")

    def test_non_regular_input_does_not_block(self):
        path = self.root / "fifo"
        os.mkfifo(path)
        self.assertEqual(diag.read_text(path)["reason"], "not_regular_file")

    def test_file_reads_are_bounded(self):
        path = self.root / "large"
        path.write_text("x" * 100)
        result = diag.read_text(path, 8)
        self.assertEqual(result, {"status": "TRUNCATED", "text": "xxxxxxxx"})

    def test_fields_exclude_unrequested_values(self):
        result = diag.parse_fields('ID=ubuntu\nPASSWORD=secret\nVERSION_ID="22.04"', {"ID", "VERSION_ID"}, "=")
        self.assertEqual(result, {"ID": "ubuntu", "VERSION_ID": "22.04"})

    def test_vmalloc_aggregation_does_not_emit_addresses(self):
        result = diag.summarize_vmalloc("0xffff-0xfffe 4096 bpf_jit_alloc_exec pages=1\n"
                                        "0xfffa-0xfffb 8192 module_alloc pages=2\n")
        self.assertEqual(result["bpf_labeled_bytes"], 4096)
        self.assertEqual(result["module_alloc_labeled_bytes"], 8192)
        self.assertNotIn("0xffff", json.dumps(result))
        self.assertIn("zero does not exclude exhaustion", result["interpretation"])

    def test_vmalloc_empty_is_not_a_no_exhaustion_claim(self):
        result = diag.summarize_vmalloc("")
        self.assertEqual(result["bpf_labeled_regions"], 0)
        self.assertIn("Not bpf_jit_current", result["interpretation"])

    def test_process_counts_are_references_not_unique_filters(self):
        for pid in (1, 2):
            folder = self.root / str(pid)
            folder.mkdir()
            (folder / "status").write_text("Name:\tworker\nSeccomp:\t2\nSeccomp_filters:\t3\n")
        result = diag.summarize_processes(self.root)
        self.assertEqual(result["filter_mode_processes"], 2)
        self.assertEqual(result["sum_reported_filter_references"], 6)
        self.assertEqual(result["max_reported_filters_per_process"], 3)
        self.assertIn("not a unique allocation count", result["interpretation"])

    def test_process_collection_reports_truncation(self):
        for pid in (1, 2):
            folder = self.root / str(pid)
            folder.mkdir()
            (folder / "status").write_text("Name:\tworker\n")
        result = diag.summarize_processes(self.root, limit=1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["status"], "PARTIAL")

    def test_installed_package_parser(self):
        rows = diag.summarize_packages("runc\t1.2.3\tinstall ok installed\nold\t1\tdeinstall ok config-files\n")
        self.assertEqual(rows, [{"package": "runc", "version": "1.2.3"}])

    def collect_command(self, name, **overrides):
        """Exercise collect with one command result and readable unrelated sources."""
        completed = {"status": "COMPLETED", "returncode": 0, "stdout": "", "stderr": ""}
        result = {**completed, **overrides}
        with patch.object(diag, "read_text", return_value={"status": "READ", "text": "0"}):
            with patch.object(diag, "summarize_processes", return_value={"status": "READ"}):
                with patch.object(diag, "run_readonly", side_effect=(
                    lambda command: result if command == name else completed
                )):
                    return diag.collect()

    def test_package_inventory_accepts_only_expected_absent_alternatives(self):
        report = self.collect_command(
            "packages", returncode=1,
            stdout="docker-ce\t5:28.0.1\tinstall ok installed\n"
                   "libseccomp2:amd64\t2.5.3\tinstall ok installed\n",
            stderr="dpkg-query: no packages found matching docker.io\n"
                   "dpkg-query: no packages found matching containerd\n")
        self.assertEqual(report["collection_status"], "COMPLETE")
        self.assertEqual(report["packages"]["returncode"], 1)
        self.assertEqual(report["packages"]["summary"], [
            {"package": "docker-ce", "version": "5:28.0.1"},
            {"package": "libseccomp2:amd64", "version": "2.5.3"}])

    def test_package_inventory_accepts_absent_requested_kernel_pattern(self):
        report = self.collect_command(
            "packages", returncode=1, stdout="runc\t1.2.3\tinstall ok installed\n",
            stderr="dpkg-query: no packages found matching linux-image-*\n")
        self.assertNotIn("packages", report["collection_gaps"])

    def test_package_inventory_keeps_unexplained_or_mixed_errors_as_gaps(self):
        missing = "dpkg-query: no packages found matching docker.io\n"
        for stderr in ("", "dpkg-query: error: cannot read database sentinel-secret\n",
                       missing + "dpkg-query: error: database corrupt sentinel-secret\n",
                       "dpkg-query: no packages found matching unrelated-package\n",
                       "dpkg-query: no packages found matching docker.io extra\n"):
            with self.subTest(stderr=stderr):
                report = self.collect_command(
                    "packages", returncode=1,
                    stdout="runc\t1.2.3\tinstall ok installed\n", stderr=stderr)
                self.assertIn("packages", report["collection_gaps"])
                self.assertEqual(report["collection_status"], "PARTIAL")
                self.assertNotIn("sentinel-secret", json.dumps(report))

    def test_package_inventory_requires_usable_rows_for_partial_query(self):
        for stdout in ("", "malformed output\n", "runc\t1.2.3\tdeinstall ok config-files\n"):
            with self.subTest(stdout=stdout):
                report = self.collect_command(
                    "packages", returncode=1, stdout=stdout,
                    stderr="dpkg-query: no packages found matching docker.io\n")
                self.assertIn("packages", report["collection_gaps"])

    def test_package_inventory_does_not_accept_other_failure_codes(self):
        for code in (2, -9, None):
            with self.subTest(code=code):
                report = self.collect_command(
                    "packages", returncode=code, stdout="runc\t1.2.3\tinstall ok installed\n",
                    stderr="dpkg-query: no packages found matching docker.io\n")
                self.assertIn("packages", report["collection_gaps"])

    def test_expected_absent_packages_cannot_hide_incomplete_collection(self):
        for status in ("TIMEOUT", "TRUNCATED", "UNAVAILABLE"):
            with self.subTest(status=status):
                report = self.collect_command(
                    "packages", status=status, returncode=1,
                    stdout="runc\t1.2.3\tinstall ok installed\n",
                    stderr="dpkg-query: no packages found matching docker.io\n")
                self.assertIn("packages", report["collection_gaps"])

    def test_successful_package_inventory_stays_complete(self):
        report = self.collect_command("packages", stdout="runc\t1.2.3\tinstall ok installed\n")
        self.assertEqual(report["collection_status"], "COMPLETE")

    def test_journal_privilege_warning_with_zero_exit_is_a_gap(self):
        report = self.collect_command(
            "kernel_log", stderr="Hint: You are currently not seeing messages from other users and the system.\n"
                                 "      Users in groups 'adm', 'systemd-journal' can see all messages.\n"
                                 "      Pass -q to turn off this notice.\n")
        self.assertIn("kernel_log", report["collection_gaps"])
        self.assertEqual(report["collection_status"], "PARTIAL")
        self.assertEqual(report["kernel_log"]["returncode"], 0)
        self.assertEqual(report["kernel_log"]["collection_gap_reason"], "journal_diagnostics_present")

    def test_visible_journal_messages_do_not_hide_access_gaps(self):
        report = self.collect_command(
            "kernel_log", stdout="seccomp filter error\n",
            stderr="Warning: some journal files were not opened due to insufficient permissions.\n")
        self.assertIn("kernel_log", report["collection_gaps"])
        self.assertEqual(report["kernel_log"]["summary"]["matching_line_counts"]["seccomp"], 1)

    def test_unknown_journal_diagnostics_remain_gaps_without_raw_stderr(self):
        report = self.collect_command("kernel_log", stderr="Unreadable journal /private/sentinel-secret\n")
        self.assertIn("kernel_log", report["collection_gaps"])
        self.assertNotIn("sentinel-secret", json.dumps(report))

    def test_empty_readable_journal_is_not_a_collection_gap(self):
        for stdout in ("", "-- No entries --\n"):
            with self.subTest(stdout=stdout):
                report = self.collect_command("kernel_log", stdout=stdout, stderr="\n")
                self.assertEqual(report["collection_status"], "COMPLETE")
                self.assertNotIn("collection_gap_reason", report["kernel_log"])
                self.assertEqual(report["kernel_log"]["summary"]["matching_line_counts"]["seccomp"], 0)

    def test_failed_or_incomplete_commands_remain_gaps(self):
        for name in diag.COMMANDS:
            for overrides in ({"returncode": 1}, {"status": "TIMEOUT"},
                              {"status": "TRUNCATED"}, {"status": "UNAVAILABLE"}):
                with self.subTest(name=name, overrides=overrides):
                    report = self.collect_command(name, **overrides)
                    self.assertIn(name, report["collection_gaps"])
                    self.assertEqual(report["collection_status"], "PARTIAL")

    def test_apt_candidates_exclude_repository_urls(self):
        result = diag.summarize_candidates("runc:\n  Installed: 1.2\n  Candidate: 1.3\n"
                                           "    500 https://user:secret@example.invalid stable\n")
        self.assertEqual(result, {"runc": {"installed": "1.2", "candidate": "1.3"}})

    def test_kernel_summary_does_not_echo_raw_logs(self):
        result = diag.summarize_log("seccomp sentinel-secret\nBPF allocation failure\n")
        self.assertEqual(result["matching_line_counts"]["seccomp"], 1)
        self.assertNotIn("sentinel-secret", json.dumps(result))

    def test_no_match_is_not_no_failure(self):
        self.assertIn("does not rule out failure", diag.summarize_log("")["interpretation"])

    def test_unknown_command_is_rejected_before_execution(self):
        with patch.object(diag.subprocess, "Popen") as execute:
            with self.assertRaises(KeyError):
                diag.run_readonly("restart-docker")
        execute.assert_not_called()

    def test_command_surface_has_no_daemon_or_mutation_operations(self):
        self.assertEqual(set(diag.COMMANDS), {"packages", "candidates", "kernel_log"})
        self.assertEqual(diag.COMMANDS["candidates"][:2], ("apt-cache", "policy"))
        self.assertEqual(diag.COMMANDS["packages"][0], "dpkg-query")
        self.assertEqual(diag.COMMANDS["kernel_log"][0], "journalctl")

    def test_hostname_mismatch_aborts_before_collection(self):
        with patch.object(diag.platform, "node", return_value="wrong-host"):
            with patch.object(diag, "collect") as collect:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = diag.main(["--expected-hostname", "server-a"])
        self.assertEqual(code, 2)
        collect.assert_not_called()

    def test_collector_never_certifies_restore_or_deployment(self):
        with patch.object(diag, "read_text", return_value={"status": "UNAVAILABLE"}):
            with patch.object(diag, "run_readonly", return_value={"status": "UNAVAILABLE"}):
                with patch.object(diag, "summarize_processes", return_value={"status": "UNAVAILABLE"}):
                    result = diag.collect()
        self.assertEqual(result["collection_status"], "PARTIAL")
        self.assertEqual(result["host_repair"], "NOT_PERFORMED")
        self.assertEqual(result["restore_test"], "NOT_RUN")
        self.assertFalse(result["production_deployment_authorized"])
        self.assertEqual(result["diagnosis"]["bpf_jit_exhaustion"], "NOT_ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
