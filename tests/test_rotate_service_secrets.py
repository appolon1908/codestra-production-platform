import csv
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rotate_service_secrets.py"
FIELDS = [
    "service", "secret_id", "host_path", "container_path", "uid", "gid",
    "mode", "read_only", "restart_command", "read_check", "health_check",
    "new_auth_check", "old_auth_check",
]


def make_case(tmp_path: Path, *, uid=None, gid=None, mode="0400",
              health="true", old="false", destination_kind="file"):
    uid = os.getuid() if uid is None else uid
    gid = os.getgid() if gid is None else gid
    secrets, values = tmp_path / "secrets", tmp_path / "values"
    secrets.mkdir()
    values.mkdir()
    target = secrets / "credential"
    if destination_kind == "file":
        target.write_bytes(b"old-value")
        target.chmod(int(mode, 8))
    elif destination_kind == "directory":
        target.mkdir()
    elif destination_kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"old-value")
        target.symlink_to(outside)
    (values / "credential").write_bytes(b"new-value")
    manifest = tmp_path / "manifest.tsv"
    row = [
        "service", "credential", str(target), "/run/secrets/credential",
        str(uid), str(gid), mode, "true", "true", "test -r " + str(target),
        health, "true", old,
    ]
    with manifest.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerow(row)
    return manifest, secrets, values, target


def invoke(tmp_path: Path, manifest: Path, secrets: Path, values: Path, *extra):
    evidence = tmp_path / "evidence.json"
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--manifest", str(manifest),
        "--service", "service", "--values-dir", str(values),
        "--approved-root", str(secrets), "--evidence", str(evidence), *extra,
    ], capture_output=True)
    return result, evidence


class RotationTests(unittest.TestCase):
    def case(self, **kwargs):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name), make_case(Path(temporary.name), **kwargs)

    def test_atomic_replacement_preserves_approved_ownership_and_permissions(self):
        tmp_path, (manifest, secrets, values, target) = self.case()
        inode_before = target.stat().st_ino
        result, evidence = invoke(tmp_path, manifest, secrets, values)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b"new-value")
        self.assertNotEqual(target.stat().st_ino, inode_before)
        self.assertEqual(
            (target.stat().st_uid, target.stat().st_gid), (os.getuid(), os.getgid())
        )
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o400)
        self.assertIs(json.loads(evidence.read_text())["contains_secret_values"], False)

    def test_missing_numeric_owner_is_rejected(self):
        for uid, gid in (("", "1"), ("1", "")):
            with self.subTest(uid=uid, gid=gid):
                tmp_path, (manifest, secrets, values, target) = self.case()
                text = manifest.read_text().splitlines()
                fields = text[1].split("\t")
                fields[4], fields[5] = uid, gid
                manifest.write_text(text[0] + "\n" + "\t".join(fields) + "\n")
                result, _ = invoke(tmp_path, manifest, secrets, values)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(target.read_bytes(), b"old-value")

    def test_nobody_nogroup_is_rejected(self):
        tmp_path, (manifest, secrets, values, target) = self.case(
            uid=65534, gid=65534
        )
        result, _ = invoke(tmp_path, manifest, secrets, values)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_bytes(), b"old-value")

    def test_unsafe_destination_is_rejected(self):
        for kind in ("directory", "symlink"):
            with self.subTest(kind=kind):
                tmp_path, (manifest, secrets, values, _) = self.case(
                    destination_kind=kind
                )
                result, _ = invoke(tmp_path, manifest, secrets, values)
                self.assertEqual(result.returncode, 1)

    def test_broad_mode_is_rejected(self):
        tmp_path, (manifest, secrets, values, target) = self.case(mode="0444")
        result, _ = invoke(tmp_path, manifest, secrets, values)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_bytes(), b"old-value")

    def test_failed_chown_rolls_back_without_partial_replacement(self):
        tmp_path, (manifest, secrets, values, target) = self.case()
        result, evidence = invoke(
            tmp_path, manifest, secrets, values, "--fault", "chown"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_bytes(), b"old-value")
        self.assertEqual(json.loads(evidence.read_text())["rollback"], "PASS")

    def test_failed_health_check_rolls_back(self):
        tmp_path, (manifest, secrets, values, target) = self.case(health="false")
        result, evidence = invoke(tmp_path, manifest, secrets, values)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_bytes(), b"old-value")
        self.assertEqual(json.loads(evidence.read_text())["rollback"], "PASS")

    def test_old_credential_remaining_valid_rolls_back(self):
        tmp_path, (manifest, secrets, values, target) = self.case(old="true")
        result, evidence = invoke(tmp_path, manifest, secrets, values)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_bytes(), b"old-value")
        self.assertEqual(json.loads(evidence.read_text())["rollback"], "PASS")

    def test_no_secret_leakage_in_output_or_evidence(self):
        tmp_path, (manifest, secrets, values, _) = self.case(
            health="printf super-secret >&2; false"
        )
        result, evidence = invoke(tmp_path, manifest, secrets, values)
        combined = result.stdout + result.stderr + evidence.read_bytes()
        self.assertNotIn(b"super-secret", combined)
        self.assertNotIn(b"new-value", combined)
        self.assertNotIn(b"old-value", combined)

    def test_manifest_has_five_distinct_service_owners_and_no_names(self):
        with (ROOT / "config" / "secret-ownership-manifest.tsv").open() as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        owners = {(row["service"], row["uid"], row["gid"]) for row in rows}
        self.assertEqual(owners, {
            ("postgres", "0", "0"), ("redis", "999", "1000"),
            ("odoo", "100", "101"), ("n8n", "1000", "1000"),
            ("middleware", "10001", "999"),
        })
        self.assertFalse(
            {"nobody", "nogroup", "odoo", "postgres", "n8n"}
            & {row["uid"] for row in rows}
        )


if __name__ == "__main__":
    unittest.main()
