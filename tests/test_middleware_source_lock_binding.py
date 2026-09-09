"""Keep selected source, signed evidence and operator documentation in one tuple.

These are source-consistency checks, not live signature verification, staging
certification, or permission to change the existing fail-closed readiness gates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'evidence/server65/middleware-4668de7-release-manifest.v1.json'


def document(path: str) -> dict:
    text = (ROOT / path).read_text(encoding='utf-8')
    return yaml.safe_load(text) if path.endswith('.yaml') else json.loads(text)


def assert_binding(lock: dict, release: dict, approved: dict, manifest: dict) -> None:
    selected = lock['middleware_authorities']['protected_production_tuple']
    candidate = lock['middleware_authorities']['appolon_n8n_gap_candidate']
    expected = {
        'repository': manifest['repository'],
        'source_sha': release['middleware_source_sha'],
        'image': manifest['image']['repository'],
        'image_digest': release['middleware_digest'],
        'migration_head': approved['required_database_head'],
    }
    for field, value in expected.items():
        assert selected[field] == value, f'selected {field}'
        assert candidate[field] == value, f'candidate {field}'
    assert approved['revision'] == expected['source_sha']
    assert approved['source'] == 'https://github.com/' + expected['repository']
    assert approved['image'] == expected['image'] + '@' + expected['image_digest']
    assert manifest['source']['git_sha'] == expected['source_sha']
    assert manifest['image']['reference'] == approved['image']
    assert manifest['runtime']['schema_or_migration_head'] == expected['migration_head']
    assert candidate['release_id'] == manifest['release_id']
    assert str(candidate['release_run']) == release['middleware_run_id']
    assert candidate['release_run'] == manifest['build']['run_id']
    assert candidate['release_run_attempt'] == manifest['build']['run_attempt']
    assert candidate['release_artifact'] == release['middleware_artifact']
    assert candidate['release_artifact'] == (
        f"signed-middleware-release-{expected['source_sha']}-"
        f"{candidate['release_run']}-{candidate['release_run_attempt']}"
    )
    assert candidate['sbom_sha256'] == 'sha256:' + release['middleware_sbom_sha256']
    for field, artifact in (
        ('sbom_sha256', 'sbom'),
        ('contracts_sha256', 'contracts_bundle'),
        ('migrations_sha256', 'migrations_bundle'),
        ('runtime_profiles_sha256', 'runtime_profiles'),
    ):
        assert candidate[field] == manifest['artifacts'][artifact]['sha256'], field


def test_selected_source_matches_release_tuple_even_while_readiness_is_blocked():
    lock = document('PRODUCTION-SOURCE-LOCK.yaml')
    release = document('config/production-release-tuple.json')
    approved = document('deploy/middleware/approved-release-lock.json')
    selected = lock['middleware_authorities']['protected_production_tuple']
    assert selected['source_sha'] == release['middleware_source_sha']
    assert selected['image_digest'] == release['middleware_digest']
    assert selected['migration_head'] == approved['required_database_head']


def test_documented_openai_tuple_matches_disabled_worker_lock():
    approved = document('deploy/middleware/openai-provider-release-lock.json')
    text = (ROOT / 'docs/OPENAI-PROVIDER-PRODUCTION-ACTIVATION.md').read_text()
    for label, field in (
        ('source SHA', 'source_revision'),
        ('image', 'image'),
        ('required database head', 'required_database_head'),
    ):
        values = re.findall(rf'^- {re.escape(label)}: `([^`]+)`$', text, re.MULTILINE)
        assert values == [approved[field]], label
    assert 'does not activate the provider' in text


def test_signed_manifest_snapshot_and_all_selected_bindings():
    lock = document('PRODUCTION-SOURCE-LOCK.yaml')
    candidate = lock['middleware_authorities']['appolon_n8n_gap_candidate']
    assert candidate['release_manifest'] == MANIFEST
    manifest_bytes = (ROOT / MANIFEST).read_bytes()
    assert 'sha256:' + hashlib.sha256(manifest_bytes).hexdigest() == candidate['release_manifest_sha256']
    workflow = (ROOT / '.github/workflows/protected-release.yml').read_text()
    digest = re.search(r'^\s+EXPECTED_ARTIFACT_DIGEST: (sha256:[0-9a-f]{64})$', workflow, re.MULTILINE)
    assert digest is not None
    assert candidate['release_artifact_digest'] == digest.group(1)
    assert candidate['derived_provenance_sha256'] == 'sha256:' + document('config/production-release-tuple.json')['middleware_provenance_sha256']
    assert candidate['derived_openvex_sha256'] == 'sha256:' + document('config/production-release-tuple.json')['middleware_openvex_sha256']
    assert_binding(lock, document('config/production-release-tuple.json'),
                   document('deploy/middleware/approved-release-lock.json'), json.loads(manifest_bytes))


def test_source_lock_generation_is_not_older_than_selected_release():
    lock = document('PRODUCTION-SOURCE-LOCK.yaml')
    manifest = document(MANIFEST)
    generated_at = datetime.fromisoformat(lock['generated_at'].replace('Z', '+00:00'))
    built_at = datetime.fromisoformat(manifest['build']['built_at'].replace('Z', '+00:00'))
    assert generated_at >= built_at


@pytest.mark.parametrize('section', ['protected_production_tuple', 'appolon_n8n_gap_candidate'])
@pytest.mark.parametrize('field', ['repository', 'source_sha', 'image', 'image_digest', 'migration_head'])
def test_any_selected_tuple_drift_is_rejected(section, field):
    lock = copy.deepcopy(document('PRODUCTION-SOURCE-LOCK.yaml'))
    lock['middleware_authorities'][section][field] = 'stale-or-mixed-authority'
    with pytest.raises(AssertionError, match=field):
        assert_binding(lock, document('config/production-release-tuple.json'),
                       document('deploy/middleware/approved-release-lock.json'), document(MANIFEST))


@pytest.mark.parametrize('field', [
    'release_id', 'release_run', 'release_run_attempt', 'release_artifact',
    'sbom_sha256', 'contracts_sha256', 'migrations_sha256', 'runtime_profiles_sha256',
])
def test_old_release_evidence_cannot_be_relabelled_as_new_candidate(field):
    lock = copy.deepcopy(document('PRODUCTION-SOURCE-LOCK.yaml'))
    lock['middleware_authorities']['appolon_n8n_gap_candidate'][field] = 'old-evidence'
    with pytest.raises(AssertionError):
        assert_binding(lock, document('config/production-release-tuple.json'),
                       document('deploy/middleware/approved-release-lock.json'), document(MANIFEST))


def test_binding_update_does_not_claim_recovery_or_runtime_admission():
    lock = document('PRODUCTION-SOURCE-LOCK.yaml')
    candidate = lock['middleware_authorities']['appolon_n8n_gap_candidate']
    assert lock['status'] == 'FAIL'
    assert lock['blockers']
    assert lock['release_readiness']['production_certified'] is False
    assert lock['release_readiness']['deployment_authorized'] is False
    assert lock['release_readiness']['source_lock_status'] == 'FAIL'
    assert 'PENDING' in lock['middleware_authorities']['protected_production_tuple']['authority_state']
    assert candidate['runtime_state'] == 'SIGNED_IMMUTABLE_CANDIDATE_NOT_DEPLOYED'
    assert candidate['external_effects_default'] == 'DISABLED'
    assert candidate['production_promotion_gate_scope'] == 'SIGNED_RELEASE_ADMISSION_ONLY_NOT_RUNTIME_DEPLOYMENT'
    assert document('config/signing-authority-rotation.json')['production_delivery_authorized'] is False


def validate_retained_manifest(manifest):
    from tools.signed_middleware_release import _validate_manifest

    retained = document(MANIFEST)
    _validate_manifest(
        manifest,
        expected_repository=retained['repository'],
        expected_image_repository=retained['image']['repository'],
        expected_workflow_identity=retained['build']['workflow_identity'],
        expected_source_sha=retained['source']['git_sha'],
        expected_image_digest=retained['image']['digest'],
        expected_run_id=str(retained['build']['run_id']),
    )


def test_retained_manifest_passes_runtime_structural_validator():
    validate_retained_manifest(document(MANIFEST))


@pytest.mark.parametrize('section,field,value', [
    ('verification', 'transparency_log_required', 1),
    ('verification', 'transparency_log_required', 1.0),
    ('promotion', 'staging_and_production_same_digest', 1),
    ('promotion', 'mutable_tags_authoritative', 0),
    ('promotion', 'mutable_tags_authoritative', 0.0),
])
def test_manifest_policy_requires_json_booleans(section, field, value):
    from tools.signed_middleware_release import SignedReleaseError

    manifest = document(MANIFEST)
    manifest[section][field] = value
    with pytest.raises(SignedReleaseError, match='not canonical'):
        validate_retained_manifest(manifest)


@pytest.mark.parametrize('reference', [
    'python:3.12@sha256:',
    'python:3.12@sha256:1234',
    'python:3.12@sha256:' + 'z' * 64,
    '@sha256:' + 'a' * 64,
    'python:3.12@sha256:' + 'a' * 64 + ':latest',
])
def test_manifest_base_image_requires_complete_immutable_reference(reference):
    from tools.signed_middleware_release import SignedReleaseError

    manifest = document(MANIFEST)
    manifest['image']['base_image'] = reference
    with pytest.raises(SignedReleaseError, match='base image is not immutable'):
        validate_retained_manifest(manifest)
