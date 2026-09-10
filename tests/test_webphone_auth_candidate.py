
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "webphone_candidate", ROOT / "scripts/run_webphone_auth_candidate.py")
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateModelTests(unittest.TestCase):
    def setUp(self):
        self.image = "registry.example/app@sha256:" + "1" * 64
        service = {"image": self.image, "environment": {
            "PROVISIONING_SERVICE_CLIENT_ID": "codestra-provisioning-service-staging",
            "PROVISIONING_SERVICE_CLIENT_SECRET_FILE": "/run/secrets/provisioning/client_secret",
            "LIVE_PSTN_DIALING": "false",
        }, "volumes": [], "networks": {"private": {}}}
        self.before = {"services": {candidate.SERVICE: service, "unrelated": {"image": "existing"}},
                       "networks": {"private": {"external": True}}}
        self.after = copy.deepcopy(self.before)
        target = self.after["services"][candidate.SERVICE]
        target["environment"].update(
            PROVISIONING_SERVICE_CLIENT_ID="codestra-provisioning-service",
            PROVISIONING_SERVICE_CLIENT_SECRET_FILE="/run/secrets/provisioning/production-client-secret")
        target["volumes"].append({
            "type": "bind", "read_only": True, "bind": {"create_host_path": False},
            "source": "/etc/codestra/secrets/codestra-compose/provisioning/production-client-secret",
            "target": "/run/secrets/provisioning/production-client-secret"})
        self.running = {"Config": {"Image": self.image, "Env": [
            k + "=" + v for k, v in service["environment"].items()]}}

    def test_only_candidate_identity_and_mount_can_change(self):
        result = candidate.validate_models(self.before, self.after, self.running)
        self.assertEqual(result["image"], self.image)

    def test_other_services_networks_and_call_flags_are_rejected(self):
        for mutation in ["service", "network", "calling"]:
            after = copy.deepcopy(self.after)
            if mutation == "service":
                after["services"]["unrelated"]["image"] = "changed"
            elif mutation == "network":
                after["networks"]["private"]["external"] = False
            else:
                after["services"][candidate.SERVICE]["environment"]["LIVE_PSTN_DIALING"] = "true"
            with self.assertRaises(ValueError):
                candidate.validate_models(self.before, after, self.running)

    def test_runtime_drift_or_new_image_is_rejected(self):
        for mutation in ["mutable_image", "different_digest", "runtime_env"]:
            after, running = copy.deepcopy(self.after), copy.deepcopy(self.running)
            if mutation == "mutable_image":
                after["services"][candidate.SERVICE]["image"] = "registry.example/app:latest"
            elif mutation == "different_digest":
                running["Config"]["Image"] = "registry.example/app@sha256:" + "2" * 64
            else:
                running["Config"]["Env"][-1] = "LIVE_PSTN_DIALING=true"
            with self.assertRaises(ValueError):
                candidate.validate_models(self.before, after, running)

    def test_writable_or_auto_created_credential_mount_is_rejected(self):
        for field in ["read_only", "bind"]:
            after = copy.deepcopy(self.after)
            after["services"][candidate.SERVICE]["volumes"][0][field] = (
                False if field == "read_only" else {"create_host_path": True})
            with self.assertRaises(ValueError):
                candidate.validate_models(self.before, after, self.running)
