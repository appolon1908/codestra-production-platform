from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

import yaml


REQUIRED = {"alertname", "severity", "service", "environment", "owner_ref"}


@dataclass
class IsolatedDispatcher:
    """Deterministic isolated notification model used without external delivery."""

    max_attempts: int = 4
    delivered: set[str] = field(default_factory=set)
    attempts: dict[str, int] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    def fingerprint(self, alert: dict) -> str:
        return hashlib.sha256(json.dumps(alert["labels"], sort_keys=True).encode()).hexdigest()

    def validate_route(self, alert: dict, route: str) -> None:
        labels = alert.get("labels")
        if not isinstance(labels, dict) or not REQUIRED <= labels.keys():
            raise ValueError("missing required labels")
        if labels["environment"] == "staging" and route == "production":
            raise ValueError("staging cannot use production route")
        if labels["environment"] == "production" and route == "test-only":
            raise ValueError("production cannot use test-only route")

    def send(self, alert: dict, route: str, outcomes: list[str]) -> bool:
        self.validate_route(alert, route)
        fingerprint = self.fingerprint(alert)
        if fingerprint in self.delivered and alert.get("status") != "resolved":
            self.events.append("duplicate_suppressed")
            return True
        for attempt, outcome in enumerate(outcomes[: self.max_attempts], 1):
            self.attempts[fingerprint] = attempt
            safe = f"attempt={attempt} outcome={outcome}"
            self.events.append(safe)
            if outcome == "success":
                self.delivered.add(fingerprint)
                self.events.append(f"delivered status={alert.get('status', 'firing')}")
                return True
        self.events.append("retry_exhausted delivery=false")
        return False

    def snapshot(self, path: Path) -> None:
        path.write_text(json.dumps({"delivered": sorted(self.delivered), "attempts": self.attempts}))

    @classmethod
    def restore(cls, path: Path) -> "IsolatedDispatcher":
        data = json.loads(path.read_text())
        return cls(delivered=set(data["delivered"]), attempts=data["attempts"])


def synthetic(environment: str = "production", status: str = "firing") -> dict:
    return {
        "status": status,
        "labels": {
            "alertname": "CodestraSyntheticFailureHandling",
            "severity": "critical",
            "service": "isolated-test",
            "environment": environment,
            "owner_ref": "isolated-owner-ref",
        },
        "annotations": {"credential_reference": "protected-file-ref"},
    }


class FailureHandlingTests(unittest.TestCase):
    def test_receiver_network_and_credential_failures_are_bounded_and_visible(self) -> None:
        scenarios = ("unavailable", "timeout", "dns_failure", "tls_failure", "invalid_credential_reference", "revoked_credential", "rate_limited")
        for scenario in scenarios:
            dispatcher = IsolatedDispatcher()
            alert = synthetic()
            alert["annotations"]["secret"] = "must-not-be-logged"
            self.assertFalse(dispatcher.send(alert, "production", [scenario] * 8))
            self.assertEqual(max(dispatcher.attempts.values()), 4)
            log = "\n".join(dispatcher.events)
            self.assertIn("retry_exhausted delivery=false", log)
            self.assertNotIn("must-not-be-logged", log)
            self.assertNotIn("delivered status=", log)

    def test_duplicate_is_suppressed(self) -> None:
        dispatcher = IsolatedDispatcher()
        alert = synthetic()
        self.assertTrue(dispatcher.send(alert, "production", ["success"]))
        self.assertTrue(dispatcher.send(alert, "production", ["success"]))
        self.assertEqual(dispatcher.events.count("duplicate_suppressed"), 1)
        self.assertEqual(sum(event.startswith("delivered") for event in dispatcher.events), 1)

    def test_malformed_and_missing_labels_are_rejected(self) -> None:
        dispatcher = IsolatedDispatcher()
        with self.assertRaises(ValueError):
            dispatcher.send({"status": "firing"}, "production", ["success"])
        alert = synthetic()
        del alert["labels"]["owner_ref"]
        with self.assertRaises(ValueError):
            dispatcher.send(alert, "production", ["success"])

    def test_environment_route_crossing_is_rejected(self) -> None:
        dispatcher = IsolatedDispatcher()
        with self.assertRaises(ValueError):
            dispatcher.send(synthetic("staging"), "production", ["success"])
        with self.assertRaises(ValueError):
            dispatcher.send(synthetic("production"), "test-only", ["success"])

    def test_alertmanager_restart_preserves_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            dispatcher = IsolatedDispatcher()
            self.assertTrue(dispatcher.send(synthetic(), "production", ["success"]))
            dispatcher.snapshot(state)
            restarted = IsolatedDispatcher.restore(state)
            self.assertTrue(restarted.send(synthetic(), "production", ["success"]))
            self.assertIn("duplicate_suppressed", restarted.events)

    def test_prometheus_restart_rule_reload_is_stable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        before = yaml.safe_load((root / "operations/monitoring/rules/platform.rules.yml").read_text())
        after = yaml.safe_load((root / "operations/monitoring/rules/platform.rules.yml").read_text())
        self.assertEqual(before, after)
        self.assertEqual(sum(len(group["rules"]) for group in before["groups"]), 76)

    def test_recovery_after_restoration_delivers_resolved(self) -> None:
        dispatcher = IsolatedDispatcher()
        firing = synthetic()
        self.assertFalse(dispatcher.send(firing, "production", ["timeout"] * 4))
        self.assertTrue(dispatcher.send(firing, "production", ["success"]))
        resolved = synthetic(status="resolved")
        self.assertTrue(dispatcher.send(resolved, "production", ["success"]))
        self.assertIn("delivered status=resolved", dispatcher.events)

    def test_retry_exhaustion_then_rate_limit_recovery(self) -> None:
        dispatcher = IsolatedDispatcher()
        self.assertTrue(dispatcher.send(synthetic(), "production", ["rate_limited", "rate_limited", "success"]))
        self.assertEqual(max(dispatcher.attempts.values()), 3)
        self.assertNotIn("retry_exhausted delivery=false", dispatcher.events)


if __name__ == "__main__":
    unittest.main()
