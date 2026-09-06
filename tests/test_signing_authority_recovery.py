import copy
import json
from pathlib import Path

import pytest

from tools.validate_runtime_rotation_ownership import ROOT, validate
from tools.validate_activation_request import NON_ACTIVATABLE_SHAS
from tools.validate_quarantined_recovery import RECOVERY_ACTIONS, validated_tuple
from tests.test_activation_request import request, validate as validate_activation


def contract():
    return json.loads((ROOT / 'config/runtime-secret-rotation-ownership.json').read_text())


def test_rotation_ownership_contract():
    validate(contract())


def test_email_reseller_is_a_separate_mandatory_klyrow_verifier():
    document = contract()
    entry = next(e for e in document['entries'] if e['secret_id'] == 'KLYROW_WEBHOOK_SECRET')
    reseller = next(c for c in entry['consumers'] if c['name'] == 'codestra-email-reseller-api-1')
    assert reseller['runtime_environment'] == '/etc/codestra/secrets/kyqra-telnexa/middleware.env'
    assert '--force-recreate api' in reseller['restart_boundary']
    assert 'predecessor' in reseller['old_secret_rejection']
    broken = copy.deepcopy(document)
    broken_entry = next(e for e in broken['entries'] if e['secret_id'] == 'KLYROW_WEBHOOK_SECRET')
    broken_entry['consumers'] = [c for c in broken_entry['consumers'] if c['name'] != 'codestra-email-reseller-api-1']
    with pytest.raises(ValueError, match='consumer inventory incomplete'):
        validate(broken)


def test_recovery_dispatch_has_only_fixed_non_delivery_actions():
    assert RECOVERY_ACTIONS == {
        'status', 'collect-evidence', 'disable-production-web-traffic',
        'disable-klyrow-email-delivery',
    }
    for action in RECOVERY_ACTIONS:
        values = validated_tuple(action)
        assert values['action'] == action
        assert values['protected_sha'] == next(iter(NON_ACTIVATABLE_SHAS))
    for action in {'stage', 'canary', 'rollback', 'preflight', 'activate-control-plane', 'enable-klyrow-email-delivery'}:
        with pytest.raises(ValueError, match='recovery-only'):
            validated_tuple(action)


def test_recovery_workflow_uses_current_head_and_has_no_tuple_or_shell_input():
    workflow = (ROOT / '.github/workflows/quarantined-release-recovery.yml').read_text()
    assert 'ref: ${{ github.sha }}' in workflow
    assert 'refs/heads/release/production-activation' in workflow
    assert 'inputs.protected_sha' not in workflow
    assert 'inputs.image_digest' not in workflow
    assert 'inputs.change_id' not in workflow
    assert 'inputs.maintenance_date' not in workflow
    assert 'GHCR_TOKEN' not in workflow
    assert 'canary' not in workflow
    assert 'enable-klyrow-email-delivery' not in workflow


def test_operator_digest_references_are_exact_and_current():
    import hashlib
    operator = ROOT / 'operations/production-operator/codestra-production-operator'
    expected = hashlib.sha256(operator.read_bytes()).hexdigest()
    assert expected == '02b857534da9faebe51b6921ecc626814a990eafea2f07e2fe061b5915210489'
    installer = (ROOT / 'operations/production-operator/install-server-a-operator.sh').read_text()
    readme = (ROOT / 'operations/production-operator/README.md').read_text()
    assert expected in installer
    assert expected in readme
    record = (ROOT / 'config/signing-authority-rotation.json').read_text()
    assert expected in record
    assert 'c78bc7cbf21d69611cb303d0439dfb601cc1c939de5ce93426a7c2673965097b' not in installer + readme + record


@pytest.mark.parametrize('field,value', [
    ('uid', 10001), ('mode', '0644'), ('activation_allowed', True),
    ('live_inventory_status', 'PASS'), ('external_inventory_required', False),
    ('required_checks', []), ('aliases', []), ('consumers', []),
    ('peer_owner', ''),
])
def test_incomplete_or_unsafe_rotation_contract_rejected(field, value):
    document = copy.deepcopy(contract())
    document['entries'][0][field] = value
    with pytest.raises(ValueError):
        validate(document)


@pytest.mark.parametrize('action', ['preflight', 'stage', 'canary', 'rollout-middleware', 'activate-control-plane', 'enable-klyrow-email-delivery'])
def test_unrecoverable_release_rejected_even_with_matching_manifest(tmp_path, action):
    sha = next(iter(NON_ACTIVATABLE_SHAS))
    args = request(tmp_path, sha=sha, action=action)
    manifest = json.loads(Path(args.manifest).read_text())
    manifest['commit'] = sha
    Path(args.manifest).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='non-activatable'):
        validate_activation(args)


@pytest.mark.parametrize('action', ['stage', 'canary', 'activate-control-plane', 'enable-klyrow-email-delivery'])
def test_host_operator_rejects_blocked_sha_before_runtime_access(monkeypatch, action):
    from tests.test_production_operator import OPERATOR
    monkeypatch.setattr(OPERATOR, 'load_release_config', lambda: {
        'protected_sha': next(iter(NON_ACTIVATABLE_SHAS)),
    })
    with pytest.raises(OPERATOR.OperatorError, match='non-activatable'):
        OPERATOR.execute(action)


def test_incident_record_requires_new_authority_and_no_delivery():
    record = json.loads((ROOT / 'config/signing-authority-rotation.json').read_text())
    assert record['blocked_release_sha'] in NON_ACTIVATABLE_SHAS
    assert record['status'] == 'NON_ACTIVATABLE'
    assert record['replacement_release_url'] is None
    assert record['production_delivery_authorized'] is False
    assert record['production_operator_sha256'] == '02b857534da9faebe51b6921ecc626814a990eafea2f07e2fe061b5915210489'


def test_non_activatable_release_record_is_exact():
    data = json.loads((ROOT / "config/non-activatable-releases.json").read_text())
    entry, = data["releases"]
    assert entry["protected_sha"] == "01f2676772b11919e1d79cc74d36bc5eeaa682cd"
    assert entry["status"] == "NON_ACTIVATABLE"
    assert entry["replacement_required"] is True


def test_environment_rotation_contract_is_atomic_and_complete():
    data = json.loads(
        (ROOT / "config/environment-secret-rotation-ownership.json").read_text()
    )
    env = data["environment_file"]
    assert env == {
        "path": "/etc/codestra/secrets/control-plane.env",
        "owner": "root:root",
        "mode": "0600",
        "atomic_group": "control-plane-email-authorities",
    }
    secrets = {entry["secret_id"]: entry for entry in data["secrets"]}
    assert set(secrets) == {
        "ODOO_OUTBOUND_HMAC_SECRET",
        "KLYROW_WEBHOOK_SECRET",
    }
    for entry in secrets.values():
        assert len(entry["consumers"]) >= 3
        assert entry["new_auth_check"].endswith(" new")
        assert entry["old_auth_check"].endswith(" old --expect-rejected")
    rollout = data["rollout"]
    assert any("atomically replace both" in step for step in rollout["success_order"])
    assert any("revoke predecessors" in step for step in rollout["success_order"])
    assert any("restore the complete environment" in step for step in rollout["rollback_order"])
    assert "old-key rejection result" in rollout["required_evidence"]


def test_recovery_runbook_never_embeds_key_material():
    text = (ROOT / "docs/SIGNING_AUTHORITY_RECOVERY.md").read_text()
    assert "BEGIN OPENSSH PRIVATE KEY" not in text
    assert "BEGIN PRIVATE KEY" not in text
    assert "ssh-ed25519 AAAA" not in text
    assert "codestra-release" in text
