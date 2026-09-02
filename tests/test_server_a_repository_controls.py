from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "operations" / "database-certification"
PACKAGE = ROOT / "operations" / "server-a-certification"
sys.path.insert(0, str(DATABASE))

import runtime_contract  # noqa: E402


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


firewall = load_script("server_a_firewall_repo", PACKAGE / "firewall" / "server-a-firewall.py")
governance = load_script("server_a_governance_repo", PACKAGE / "publish-governance-status.py")
centrifugo = load_script("server_a_centrifugo_repo", PACKAGE / "centrifugo-probe.py")


class RuntimeContractTests(unittest.TestCase):
    def test_remote_contract_rejects_shell_metacharacters_and_traversal(self):
        self.assertEqual(
            runtime_contract.parse_remote("backup-user@backup.example:/srv/codestra"),
            ("backup-user@backup.example", "/srv/codestra"),
        )
        for value in (
            "-oProxyCommand=x:/srv/data",
            "host;touch /tmp/x:/srv/data",
            "host:relative",
            "host:/srv/../etc",
        ):
            with self.subTest(value=value), self.assertRaises(runtime_contract.ContractError):
                runtime_contract.parse_remote(value)

    def test_safe_extract_rejects_traversal_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad = root / "bad.tar.gz"
            with tarfile.open(bad, "w:gz") as archive:
                member = tarfile.TarInfo("../escape")
                member.size = 1
                archive.addfile(member, io.BytesIO(b"x"))
            with self.assertRaises(runtime_contract.ContractError):
                runtime_contract.safe_extract_tar(bad, root / "out")


class SourceContractTests(unittest.TestCase):
    def test_database_contract_names_every_required_selective_recovery_system(self):
        payload = json.loads((DATABASE / "database-targets.json").read_text())
        names = {
            item["name"]
            for instance in payload["postgres_instances"]
            for item in instance["databases"]
        }
        self.assertTrue(
            {
                "keycloak",
                "codestra_n8n",
                "control_plane",
                "codestra_middleware_appolon",
                "beyvra_email",
                "email_reseller",
            }.issubset(names)
        )
        self.assertEqual(payload["environment"], "production")

    def test_mission_prohibits_ssh_mutation_and_business_writes(self):
        mission = (PACKAGE / "mission.yaml").read_text()
        for contract in (
            "ssh_configuration_changes: prohibited",
            "ssh_key_changes: prohibited",
            "ssh_service_restart: prohibited",
            "production_business_writes: prohibited",
            "docker_volume_deletion: prohibited",
        ):
            self.assertIn(contract, mission)


class CentrifugoTests(unittest.TestCase):
    def test_external_url_contract_is_https_and_credential_free(self):
        parsed = centrifugo.validate_url(
            "https://realtime.example/health", field="external", schemes={"https"}
        )
        self.assertEqual(parsed.scheme, "https")
        for value in (
            "http://realtime.example/health",
            "https://user:pass@realtime.example/health",
            "https://realtime.example/health?token=x",
        ):
            with self.subTest(value=value), self.assertRaises(runtime_contract.ContractError):
                centrifugo.validate_url(value, field="external", schemes={"https"})


class GovernanceTests(unittest.TestCase):
    def test_status_match_is_exact_and_idempotency_safe(self):
        state = {"state": "success", "description": "certified", "target_url": ""}
        item = {
            "context": "codestra/financial-governance",
            "state": "success",
            "description": "certified",
            "target_url": None,
        }
        self.assertTrue(
            governance.status_matches(
                item, context="codestra/financial-governance", state=state
            )
        )
        item["description"] = "different"
        self.assertFalse(
            governance.status_matches(
                item, context="codestra/financial-governance", state=state
            )
        )


class FirewallTests(unittest.TestCase):
    def test_rules_filter_original_dnat_port_and_preserve_listener(self):
        config = {
            "public_interface": "eth0",
            "private_interface": "vlan4001",
            "private_ipv4_subnets": ["10.40.0.0/24"],
            "public_tcp_ports": [80, 443],
            "public_udp_ports": [],
        }
        rules = firewall.render_rules(
            config, [{"address": "0.0.0.0", "port": 22, "protocol": "tcp"}]
        )
        self.assertIn("tcp dport 22 accept", rules)
        self.assertIn("ct original proto-dst { 80, 443 }", rules)
        self.assertIn("policy drop", rules)

    def test_ssh_comparison_allows_new_but_not_lost_sessions(self):
        common = {"files": [], "effective_settings": {}, "listeners": []}
        before = {**common, "active_sessions": [{"local": "x", "peer_sha256": "a"}]}
        after = {
            **common,
            "active_sessions": [
                {"local": "x", "peer_sha256": "a"},
                {"local": "y", "peer_sha256": "b"},
            ],
        }
        firewall.assert_ssh_state_unchanged(before, after)
        with self.assertRaises(runtime_contract.ContractError):
            firewall.assert_ssh_state_unchanged(before, {**common, "active_sessions": []})


if __name__ == "__main__":
    unittest.main()
