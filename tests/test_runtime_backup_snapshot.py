import hashlib
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "operations/readiness/snapshot_runtime.py"
spec = importlib.util.spec_from_file_location("snapshot_runtime", SOURCE)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeBackupSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.compose = self.root / "compose.yaml"
        self.compose.write_text("services: {}\n")
        self.addons = self.root / "addons"
        self.addons.mkdir()
        self.patch = self.addons / "current.js"
        self.patch.write_text("current override\n")
        self.items = [{"Name": "/" + name, "Id": name + "-id", "Image": "sha256:example",
                       "State": {"Status": "running", "Paused": False},
                       "Config": {"User": "odoo", "Labels": {
                           "com.docker.compose.project.config_files": str(self.compose)},
                           "Cmd": ["odoo", "--addons-path=/mnt/addons"]},
                       "Mounts": []} for name in runtime.CONTAINERS]
        self.by_name = {i["Name"].lstrip("/"): i for i in self.items}
        self.volumes = {}
        for alias, (name, volume_name, destination) in runtime.APPLICATION_VOLUMES.items():
            path = self.root / (alias + "-volume")
            path.mkdir()
            self.volumes[volume_name] = {"Name": volume_name, "Driver": "local",
                                         "Options": None, "Mountpoint": str(path)}
            self.by_name[name]["Mounts"].append({"Type": "volume", "Name": volume_name,
                                                "Source": str(path), "Destination": destination})
        self.by_name["codestra-odoo-1"]["Mounts"].append({"Type": "bind", "RW": False,
            "Source": str(self.patch), "Destination": "/mnt/addons/current.js"})

    def layout(self):
        return runtime.make_layout(self.items, self.volumes, [str(self.addons)])

    def test_active_override_and_compose_are_required_inside_archive(self):
        layout = self.layout()
        archive = self.root / "configuration.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.addons, arcname=str(self.addons).lstrip("/"))
            tar.add(self.compose, arcname=str(self.compose).lstrip("/"))
        runtime.verify_configuration(layout, archive)
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.addons, arcname=str(self.addons).lstrip("/"), recursive=False)
            tar.add(self.compose, arcname=str(self.compose).lstrip("/"))
        with self.assertRaisesRegex(ValueError, "missing from archive"):
            runtime.verify_configuration(layout, archive)

    def test_missing_compose_stops_preflight(self):
        self.compose.unlink()
        with self.assertRaises(FileNotFoundError):
            self.layout()

    def test_unclassified_writable_bind_stops_preflight(self):
        self.by_name["codestra-odoo-1"]["Mounts"][-1]["RW"] = True
        with self.assertRaisesRegex(ValueError, "unclassified writable"):
            self.layout()

    def test_volume_mapping_must_match_active_container(self):
        self.by_name["codestra-odoo-1"]["Mounts"][0]["Source"] = str(self.root)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.layout()

    def test_paused_container_stops_preflight(self):
        self.by_name["codestra-odoo-1"]["State"]["Paused"] = True
        with self.assertRaisesRegex(ValueError, "not running"):
            self.layout()

    def test_volume_roundtrip_retains_bytes_names_ownership_and_symlinks(self):
        layout = self.layout()
        volume = Path(layout["application_volumes"]["odoo"]["mountpoint"])
        payload = b"attachment bytes\x00" * 200
        attachment = volume / ".local/share/Odoo/filestore/codestra_odoo/ab/object"
        attachment.parent.mkdir(parents=True)
        attachment.write_bytes(payload)
        outside = self.root / "outside.txt"
        outside.write_text("must not be followed")
        (volume / "link").symlink_to(outside)
        archive = self.root / "application-volumes.tar.gz"
        runtime.archive_volumes(layout, archive)
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.getmember("odoo/.local/share/Odoo/filestore/codestra_odoo/ab/object")
            self.assertEqual(hashlib.sha256(tar.extractfile(member).read()).digest(), hashlib.sha256(payload).digest())
            self.assertEqual((member.uid, member.gid), (attachment.stat().st_uid, attachment.stat().st_gid))
            self.assertTrue(tar.getmember("odoo/link").issym())
            self.assertTrue(tar.getmember("n8n").isdir())
            self.assertNotIn("outside.txt", tar.getnames())


if __name__ == "__main__":
    unittest.main()
