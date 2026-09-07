"""Offline policy/CI regressions. No GitHub writes or server operations."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from tools import ci_merge_gate as gate
from tools import configure_checks_only_merge as setup

ROOT = Path(__file__).resolve().parents[1]


def passing():
    return {
        'checks': [{'name': name, 'status': 'completed', 'conclusion': 'success',
                    'app': {'slug': 'github-actions', 'id': 15368}} for name in ('validate', 'diagnose')],
        'statuses': [{'id': 10, 'sha': 'head', 'context': 'validate', 'state': 'success'}],
        'runs': [{'id': i, 'workflow_id': i, 'path': path, 'status': 'completed', 'conclusion': 'success'}
                 for i, path in enumerate(sorted(gate.REQUIRED_WORKFLOWS), 1)],
    }


def record():
    return {
        'id': setup.RULESET_ID, 'source': setup.REPO,
        'name': 'server65-default-branch-gates', 'target': 'branch', 'enforcement': 'active',
        'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
        'bypass_actors': [],
        'rules': [{'type': kind} for kind in ('deletion', 'non_fast_forward', 'required_linear_history')]
        + [{'type': 'pull_request', 'parameters': {
            'required_approving_review_count': 1, 'dismiss_stale_reviews_on_push': True,
            'required_reviewers': [], 'require_code_owner_review': False,
            'require_last_push_approval': False, 'required_review_thread_resolution': True,
            'require_extra_approval_for_unattributed_changes': True, 'allowed_merge_methods': ['squash'],
        }}],
    }


def test_complete_successful_snapshot_passes():
    assert gate.evaluate(passing())['state'] == 'success'


@pytest.mark.parametrize('field', ['checks', 'runs'])
def test_missing_mandatory_evidence_is_pending(field):
    snapshot = passing(); snapshot[field] = []
    assert gate.evaluate(snapshot)['state'] == 'pending'


def test_empty_snapshot_never_passes():
    assert gate.evaluate({'checks': [], 'runs': [], 'statuses': []})['state'] == 'pending'


@pytest.mark.parametrize('conclusion', ['failure', 'cancelled', 'timed_out', 'skipped', 'neutral', None])
def test_mandatory_check_requires_actual_success(conclusion):
    snapshot = passing(); snapshot['checks'][0]['conclusion'] = conclusion
    assert gate.evaluate(snapshot)['state'] == 'failure'


@pytest.mark.parametrize('conclusion', ['failure', 'cancelled', 'timed_out', 'skipped', 'neutral'])
def test_mandatory_workflow_requires_actual_success(conclusion):
    snapshot = passing(); snapshot['runs'][0]['conclusion'] = conclusion
    assert gate.evaluate(snapshot)['state'] == 'failure'


def test_wrong_check_publisher_does_not_satisfy_requirement():
    snapshot = passing(); snapshot['checks'][0]['app']['slug'] = 'untrusted-app'
    assert gate.evaluate(snapshot)['state'] == 'pending'


def test_current_pending_status_is_not_ignored():
    snapshot = passing(); snapshot['statuses'].append({'id': 11, 'sha': 'head', 'context': 'validate', 'state': 'pending'})
    assert gate.evaluate(snapshot)['state'] == 'pending'


def test_merge_failure_not_hidden_by_newer_head_success():
    snapshot = passing()
    snapshot['statuses'].append({'id': 9, 'sha': 'merge', 'context': 'validate', 'state': 'failure'})
    assert gate.evaluate(snapshot)['state'] == 'failure'


def test_fixed_status_rerun_supersedes_failure_on_same_commit():
    snapshot = passing()
    snapshot['statuses'].append({'id': 9, 'sha': 'head', 'context': 'validate', 'state': 'failure'})
    assert gate.evaluate(snapshot)['state'] == 'success'


def test_late_running_optional_workflow_blocks():
    snapshot = passing()
    snapshot['runs'].append({'id': 20, 'workflow_id': 20, 'path': 'optional.yml', 'status': 'queued', 'conclusion': None})
    assert gate.evaluate(snapshot)['state'] == 'pending'


def test_self_gate_does_not_deadlock():
    snapshot = passing()
    snapshot['checks'] += [{'name': name, 'status': 'queued', 'app': {'slug': 'github-actions'}} for name in gate.SELF_CHECKS]
    snapshot['runs'].append({'id': 20, 'workflow_id': 20, 'path': gate.SELF_WORKFLOW, 'status': 'in_progress'})
    assert gate.evaluate(snapshot)['state'] == 'success'


def test_same_named_foreign_check_is_not_excluded():
    snapshot = passing()
    snapshot['checks'].append({'name': 'production-gate', 'status': 'completed', 'conclusion': 'failure', 'app': {'slug': 'other'}})
    assert gate.evaluate(snapshot)['state'] == 'failure'


def test_other_workflow_failures_are_rejected():
    snapshot = passing()
    snapshot['runs'].append({'id': 20, 'workflow_id': 20, 'path': 'container.yml', 'status': 'completed', 'conclusion': 'failure'})
    assert gate.evaluate(snapshot)['state'] == 'failure'


def test_permission_failure_does_not_turn_into_empty_success(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['ci_merge_gate', '--repo', setup.REPO, '--pr', '1', '--head', 'a' * 40, '--base', 'b' * 40])
    monkeypatch.setattr(gate.time, 'sleep', lambda _: None)
    def denied(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ['gh', 'api'])
    monkeypatch.setattr(gate, 'gh_json', denied)
    assert gate.main() == 1


def test_branch_movement_blocks_before_fetching_tests(monkeypatch):
    replies = iter([{'state': 'open', 'head': {'sha': 'a' * 40}, 'base': {'ref': setup.BRANCH}},
                    {'object': {'sha': 'c' * 40}}])
    monkeypatch.setattr(gate, 'gh_json', lambda *a, **k: next(replies))
    with pytest.raises(ValueError, match='target branch advanced'):
        gate.collect(setup.REPO, 1, 'a' * 40, 'b' * 40)


def test_behind_branch_cannot_merge_even_with_successful_tests(monkeypatch):
    replies = iter([{'state': 'open', 'head': {'sha': 'a' * 40}, 'base': {'ref': setup.BRANCH}},
                    {'object': {'sha': 'b' * 40}}, {'behind_by': 1}])
    monkeypatch.setattr(gate, 'gh_json', lambda *a, **k: next(replies))
    with pytest.raises(ValueError, match='behind'):
        gate.collect(setup.REPO, 1, 'a' * 40, 'b' * 40)


def test_mandatory_workflows_have_no_skip_filters():
    for filename in ('platform-source-gate.yml', 'gitleaks-pr-diagnostics.yml', 'production-merge-gate.yml'):
        workflow = yaml.load((ROOT / '.github/workflows' / filename).read_text(), Loader=yaml.BaseLoader)
        assert workflow['on']['pull_request'] in ('', None, {})
    workflow = yaml.load((ROOT / '.github/workflows/production-merge-gate.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['permissions'].values()) == {'read'}
    guard = workflow['jobs']['checks-only-policy']
    assert guard['needs'] == 'production-gate'
    assert guard['if'] == '${{ always() }}'
    assert 'test "$GATE_RESULT" = success' in guard['steps'][0]['run']


def test_transition_enforces_checks_before_lowering_review_count():
    original = record()
    first = setup.policy_payload(original, 15368, zero_reviews=False)
    final = setup.policy_payload(original, 15368, zero_reviews=True)
    get_pr = lambda p: next(r['parameters'] for r in p['rules'] if r['type'] == 'pull_request')
    assert get_pr(first)['required_approving_review_count'] == 1
    assert get_pr(final)['required_approving_review_count'] == 0
    assert get_pr(final)['required_review_thread_resolution'] is True
    assert get_pr(final)['allowed_merge_methods'] == ['squash']
    assert get_pr(final)['require_extra_approval_for_unattributed_changes'] is False
    checks = next(r['parameters'] for r in final['rules'] if r['type'] == 'required_status_checks')
    assert checks['strict_required_status_checks_policy'] is True
    assert {c['context'] for c in checks['required_status_checks']} == setup.REQUIRED
    assert all(c['integration_id'] == 15368 for c in checks['required_status_checks'])
    assert {r['type'] for r in final['rules']} >= {'deletion', 'non_fast_forward', 'required_linear_history', 'required_signatures'}
    assert final['bypass_actors'] == []
    assert original == record()


def test_preexisting_required_checks_are_preserved():
    original = record()
    original['rules'].append({'type': 'required_status_checks', 'parameters': {
        'required_status_checks': [{'context': 'security', 'integration_id': 987}],
        'strict_required_status_checks_policy': False,
    }})
    final = setup.policy_payload(original, 15368, zero_reviews=True)
    checks = next(r['parameters'] for r in final['rules'] if r['type'] == 'required_status_checks')
    assert {'context': 'security', 'integration_id': 987} in checks['required_status_checks']


@pytest.mark.parametrize('change', [
    {'id': 1}, {'source': 'someone/else'}, {'target': 'tag'}, {'enforcement': 'disabled'},
    {'conditions': {'ref_name': {'include': ['~ALL'], 'exclude': []}}},
    {'bypass_actors': [{'actor_type': 'User', 'actor_id': 1}]},
])
def test_setup_rejects_unexpected_scope_or_bypass(change):
    original = record(); original.update(change)
    with pytest.raises(ValueError):
        setup.policy_payload(original, 15368, zero_reviews=True)


def test_new_payload_can_be_applied_idempotently():
    original = record()
    final = setup.policy_payload(original, 15368, zero_reviews=True)
    updated = {**original, **final}
    assert setup.policy_payload(updated, 15368, zero_reviews=True) == final


def test_denied_admin_read_never_attempts_mutation(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['configure_checks_only_merge', '--bootstrap-pr', '1', '--expected-head', 'a' * 40, '--apply'])
    methods = []
    def fake(endpoint, method='GET', **kwargs):
        methods.append(method)
        if endpoint == 'user':
            return {'login': 'appolon1908-hue'}
        if endpoint == 'repos/' + setup.REPO:
            return {'default_branch': setup.BRANCH, 'permissions': {'admin': True}}
        if '/rulesets/' in endpoint:
            return record()
        raise subprocess.CalledProcessError(1, ['gh', 'api'])
    monkeypatch.setattr(setup, 'api', fake)
    assert setup.main() == 1
    assert set(methods) == {'GET'}
