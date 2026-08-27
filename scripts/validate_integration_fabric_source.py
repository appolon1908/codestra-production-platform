#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'config/integration-fabric'
hosts = json.loads((BASE / 'caddy-host-map.v2.json').read_text())
zones = json.loads((BASE / 'network-zones.v2.json').read_text())
capabilities = json.loads((BASE / 'capabilities.v2.json').read_text())
release = json.loads((BASE / 'release-order.v2.json').read_text())
assert hosts['public_ports'] == [80, 443]
assert hosts['public_kong_admin'] is False
assert hosts['public_n8n'] is False
assert hosts['public_databases'] is False
assert len({item['host'] for item in hosts['hosts']}) == len(hosts['hosts'])
assert all(not zone['public_ingress'] for zone in zones['zones'] if zone['id'] != 'edge-public')
assert all(value is False for key, value in capabilities.items() if key != 'schema_version')
assert release['feature_branch_deployment'] is False
assert release['live_server_mutation_from_source_pr'] is False
print('CODESTRA_RUNTIME_INTEGRATION_FABRIC_V2=PASS')
