#!/usr/bin/env python3
"""Validate central contract, composition, release, Caddy, and Kyqra authority."""
from __future__ import annotations
import json
import hashlib
import re
from pathlib import Path


def require(condition: object, message: str) -> None:
    """Raise on invalid authority even when Python optimization is enabled."""
    if not condition:
        raise ValueError(message)
ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_REPOSITORY = 'appolon1908-hue/codestra-production-platform'
AUTHORITY_BRANCH = 'release/production-activation'
CANONICAL_KYQRA_REPOSITORY = 'appolon1908-hue/kyqra-crawler'
RETIRED_KYQRA_REPOSITORY = 'appolon1908-hue/kyqra'
RELEASE_BEARING_WORKLOADS = {'caddy', 'kong', 'middleware', 'odoo-19', 'n8n', 'keycloak', 'kyqra-crawler', 'prometheus', 'alertmanager', 'node-exporter', 'postgres-exporter', 'redis-exporter', 'cadvisor', 'blackbox-exporter', 'postgresql', 'redis', 'nats-jetstream', 'temporal', 'telnexa', 'klyrow', 'middleware-external-webhook-worker', 'middleware-breero-odoo-worker', 'sms-event-worker', 'email-reseller-api', 'sms-api', 'mail-api', 'stalwart', 'kong-standby-auth', 'kong-identity-certification', 'beyvra-email-api', 'reseller-portal', 'private-vicidial-ingress', 'websocket-gateway', 'integration-control-plane'}

def load(path: str) -> dict:
    value = json.loads((ROOT / path).read_text(encoding='utf-8'))
    require(isinstance(value, dict), f'{path} must contain an object')
    return value

def validate_authority(value: dict, label: str) -> None:
    require(value.get('authority') == {'repository': AUTHORITY_REPOSITORY, 'branch': AUTHORITY_BRANCH}, f'{label} authority is not canonical')

def validate_catalog() -> None:
    catalog = load('contracts/catalog.v1.json')
    require(catalog.get('schema_version') == 'contract-catalog.v1', 'platform authority invariant failed')
    validate_authority(catalog, 'contract catalog')
    contracts = catalog.get('contracts')
    require(isinstance(contracts, list) and contracts, 'platform authority invariant failed')
    ids = [item.get('id') for item in contracts]
    require(all((isinstance(item, str) and item for item in ids)), 'platform authority invariant failed')
    require(len(ids) == len(set(ids)), 'contract IDs must be unique')
    for contract in contracts:
        source = contract.get('source', {})
        repository = source.get('repository')
        path = source.get('path')
        require(isinstance(repository, str) and repository, 'platform authority invariant failed')
        require(isinstance(path, str) and path, 'platform authority invariant failed')
        require(repository != RETIRED_KYQRA_REPOSITORY, 'platform authority invariant failed')
        if repository == AUTHORITY_REPOSITORY:
            require((ROOT / path).is_file(), f'missing catalog source: {path}')

def validate_composition() -> None:
    composition = load('composition/runtime-composition.v1.json')
    require(composition.get('schema_version') == 'runtime-composition.v1', 'platform authority invariant failed')
    validate_authority(composition, 'runtime composition')
    components = composition.get('components')
    require(isinstance(components, list) and components, 'platform authority invariant failed')
    ids = [item.get('id') for item in components]
    require(len(ids) == len(set(ids)), 'component IDs must be unique')
    by_id = {item['id']: item for item in components}
    release_service_ids = composition.get('release_service_ids')
    require(isinstance(release_service_ids, list) and release_service_ids, 'platform authority invariant failed')
    require(len(release_service_ids) == len(set(release_service_ids)), 'release service IDs must be unique')
    require(set(release_service_ids) == RELEASE_BEARING_WORKLOADS, 'release boundary must include every independently deployed workload')
    require(set(release_service_ids) == set(by_id), 'every deployed component must be release-bearing')
    require(by_id['caddy']['source_path'] == 'operations/caddy', 'platform authority invariant failed')
    require(by_id['kyqra-crawler']['source_repository'] == CANONICAL_KYQRA_REPOSITORY, 'platform authority invariant failed')
    for service_id in ('middleware', 'nats-jetstream', 'temporal'):
        require(by_id[service_id]['source_repository'] == 'Codestra-SRL/codestra-middleware', 'platform authority invariant failed')
        require(by_id[service_id]['candidate_source_repository'] == 'appolon1908-hue/Middleware-', 'platform authority invariant failed')
        require(by_id[service_id]['authority_state'] == 'unresolved-pending-governed-convergence', 'platform authority invariant failed')
    host_components = {component_id for host in composition.get('hosts', []) for component_id in host.get('components', [])}
    unresolved = host_components - set(by_id)
    require(not unresolved, f'undefined host components: {sorted(unresolved)}')
    repositories = {item.get('source_repository') for item in components}
    require(RETIRED_KYQRA_REPOSITORY not in repositories, 'platform authority invariant failed')
    for component in components:
        if component.get('source_repository') == AUTHORITY_REPOSITORY:
            require((ROOT / component['source_path']).exists(), 'platform authority invariant failed')
        composition_input = component.get('composition_input')
        if composition_input:
            require((ROOT / composition_input).is_file(), f'missing composition input: {composition_input}')

def validate_release_schema() -> None:
    schema = load('release/platform-release-manifest.v1.schema.json')
    require(schema.get('$schema') == 'https://json-schema.org/draft/2020-12/schema', 'platform authority invariant failed')
    authority = schema['properties']['authority']['properties']
    require(authority['repository']['const'] == AUTHORITY_REPOSITORY, 'platform authority invariant failed')
    require(authority['git_sha']['$ref'] == '#/$defs/git_sha', 'platform authority invariant failed')
    require(schema['$defs']['git_sha']['pattern'] == '^[0-9a-f]{40}$', 'platform authority invariant failed')
    require(schema['$defs']['image_digest']['pattern'] == '^sha256:[0-9a-f]{64}$', 'platform authority invariant failed')
    composition = load('composition/runtime-composition.v1.json')
    services = schema['properties']['services']
    required_services = {rule['contains']['properties']['service_id']['const'] for rule in services['allOf']}
    require(required_services == set(composition['release_service_ids']), 'platform authority invariant failed')
    require(services['minItems'] == services['maxItems'] == len(required_services), 'platform authority invariant failed')
    gate = schema['$defs']['environment_gate']
    evidence = gate['properties']['evidence']
    required_evidence = {'integration', 'backup', 'restore', 'monitoring', 'rollback'}
    require(set(evidence['properties']) == required_evidence | {'approval'}, 'platform authority invariant failed')
    require(set(gate['allOf'][0]['then']['properties']['evidence']['required']) == required_evidence, 'platform authority invariant failed')
    production_gate = schema['$defs']['production_gate']
    require(production_gate['allOf'][0]['$ref'] == '#/$defs/environment_gate', 'platform authority invariant failed')
    require(production_gate['allOf'][1]['$ref'] == '#/$defs/production_evidence_environment', 'platform authority invariant failed')
    require(production_gate['allOf'][2]['then']['properties']['evidence']['required'] == ['approval'], 'platform authority invariant failed')
    promotion = schema['properties']['promotion']
    require(promotion['allOf'][0]['then']['properties']['staging']['properties']['status']['const'] == 'accepted', 'platform authority invariant failed')
    edge = schema['properties']['edge']['properties']
    require(edge['caddy']['allOf'][1]['properties']['path']['const'] == 'release/caddy-edge-bundle.v1.json', 'platform authority invariant failed')
    require(edge['kong']['allOf'][1]['properties']['path']['const'] == 'deploy/kong/control-plane.yml', 'platform authority invariant failed')

def validate_caddy_bundle() -> None:
    bundle = load('release/caddy-edge-bundle.v1.json')
    require(bundle.get('schema_version') == 'caddy-edge-bundle.v1', 'platform authority invariant failed')
    require(bundle.get('authority_repository') == AUTHORITY_REPOSITORY, 'platform authority invariant failed')
    entries = bundle.get('files')
    require(isinstance(entries, list) and entries, 'platform authority invariant failed')
    paths = [entry.get('path') for entry in entries]
    expected = sorted((str(path.relative_to(ROOT)) for path in (ROOT / 'operations' / 'caddy').rglob('*') if path.is_file() and path.suffix != '.md'))
    require(sorted(paths) == expected, 'Caddy bundle must cover every deployable file')
    for entry in entries:
        path = ROOT / entry['path']
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(entry.get('sha256') == actual, f"stale Caddy bundle hash: {entry['path']}")
        require(entry.get('deployment_target') in {'container-caddy', 'host-caddy-pending'}, 'platform authority invariant failed')

def validate_caddy_home() -> None:
    caddy_root = (ROOT / 'operations/caddy/Caddyfile').read_text(encoding='utf-8')
    require('import snippets/*.caddy' in caddy_root, 'platform authority invariant failed')
    require('import api.codestra.co.caddy' in caddy_root, 'platform authority invariant failed')
    require('import auth.codestra.co.caddy' in caddy_root, 'platform authority invariant failed')
    api = (ROOT / 'operations/caddy/api.codestra.co.caddy').read_text(encoding='utf-8')
    auth = (ROOT / 'operations/caddy/auth.codestra.co.caddy').read_text(encoding='utf-8')
    snippets = (ROOT / 'operations/caddy/snippets/security-headers.caddy').read_text(encoding='utf-8')
    require('api.codestra.co' in api and 'import security_headers' in api, 'platform authority invariant failed')
    require('reverse_proxy codestra-websocket-gateway-gateway-1:8080' in api, 'Caddy WebSocket upstream must use shared-network DNS')
    require('reverse_proxy codestra-kong-kong-gateway-1:8000' in api, 'Caddy Kong upstream must use shared-network DNS')
    require('reverse_proxy 127.0.0.1:' not in api, 'container Caddy must not use loopback for cross-service upstreams')
    require('auth.codestra.co' in auth and 'import security_headers' in auth, 'platform authority invariant failed')
    require('reverse_proxy keycloak:8080' in auth, 'platform authority invariant failed')
    require(re.search('\\(security_headers\\)\\s*\\{', snippets), 'platform authority invariant failed')

def validate_release_manifest(manifest: dict) -> None:
    """Schema plus cross-environment invariants; not runtime certification."""
    from jsonschema import Draft202012Validator, ValidationError
    from pathlib import PurePosixPath
    try:
        Draft202012Validator(load('release/platform-release-manifest.v1.schema.json')).validate(manifest)
    except ValidationError as exc:
        raise ValueError('platform release manifest schema rejected') from exc
    promotion = manifest['promotion']
    if promotion['production']['status'] != 'accepted':
        return
    staging = promotion['staging']['evidence']
    production = promotion['production']['evidence']
    staging_paths: set[str] = set()
    staging_digests: set[str] = set()
    for evidence in staging.values():
        path = PurePosixPath(evidence['path'])
        require(not path.is_absolute() and '..' not in path.parts,
                'staging evidence path rejected')
        staging_paths.add(str(path))
        staging_digests.add(evidence['sha256'])
    for evidence in production.values():
        path = PurePosixPath(evidence['path'])
        require(not path.is_absolute() and '..' not in path.parts,
                'production evidence path rejected')
        require(str(path) not in staging_paths,
                'production evidence must not reuse staging artifact paths')
        require(evidence['sha256'] not in staging_digests,
                'production evidence must not reuse staging artifact bytes')


def validate_release_records(explicit: Path | None = None) -> None:
    """Gate every committed central release record and an optional CLI candidate."""
    paths = sorted((ROOT / 'release/manifests').glob('*.json'))
    if explicit is not None:
        paths.append(explicit)
    for path in paths:
        require(path.is_file() and not path.is_symlink(), 'release record path rejected')
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, 'duplicate release record key')
                result[key] = value
            return result
        def invalid_constant(value):
            raise ValueError('non-finite release record value')
        manifest = json.loads(path.read_text(encoding='utf-8'),
                              object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
        validate_release_manifest(manifest)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, help='validate an additional central release candidate')
    args = parser.parse_args()
    validate_catalog()
    validate_composition()
    validate_release_schema()
    validate_caddy_bundle()
    validate_caddy_home()
    validate_release_records(args.manifest)
    print('Platform authority validation passed: contract catalog, runtime composition, release manifest, Caddy home, and Kyqra source are canonical.')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
