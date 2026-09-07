"""Exercise cutover ordering against an in-memory API, never live GitHub."""
from copy import deepcopy
import json
import subprocess
import sys
from urllib.parse import quote

import pytest

from tools import configure_checks_only_merge as setup


HEAD = 'a' * 40
BASE = 'b' * 40
PREFIX = 'repos/' + setup.REPO
RULESET = f'{PREFIX}/rulesets/{setup.RULESET_ID}'
PROTECTION = f'{PREFIX}/branches/{quote(setup.BRANCH, safe="")}/protection'
PR = f'{PREFIX}/pulls/317'


def initial_ruleset():
    return {
        'id': setup.RULESET_ID, 'source': setup.REPO,
        'name': 'server65-default-branch-gates', 'target': 'branch',
        'enforcement': 'active', 'bypass_actors': [],
        'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
        'rules': [{'type': 'pull_request', 'parameters': {
            'required_approving_review_count': 1,
            'required_review_thread_resolution': True,
            'allowed_merge_methods': ['squash'],
        }}],
    }


class CutoverAPI:
    def __init__(self, *, classic=True, concurrent_edit=None, final_read=None):
        self.live = initial_ruleset()
        self.classic = {
            'required_pull_request_reviews': {
                **setup.REVIEW_PATCH, 'required_approving_review_count': 1,
            } if classic else None,
            'required_status_checks': {'strict': True, 'contexts': ['validate']},
            'required_signatures': {'enabled': True},
        }
        self.concurrent_edit = concurrent_edit
        self.final_read = final_read
        self.calls = []
        self.reads = 0
        self.merged = False
        self.concurrent_snapshot = None

    def __call__(self, endpoint, method='GET', payload=None, paged=False):
        self.calls.append((endpoint, method, deepcopy(payload)))
        if endpoint == RULESET:
            if method == 'GET':
                self.reads += 1
                if self.reads == 4 and self.final_read == 'denied':
                    raise subprocess.CalledProcessError(1, ['gh', 'api'])
                if self.reads == 4 and self.final_read == 'malformed':
                    return {'id': setup.RULESET_ID}
                snapshot = deepcopy(self.live)
                # Administrator changes live state AFTER the strengthened
                # readback snapshot, exactly the reported vulnerable interval.
                if self.reads == 3 and self.concurrent_edit:
                    self.concurrent_edit(self.live)
                    self.concurrent_snapshot = deepcopy(self.live)
                return snapshot
            assert method == 'PUT'
            self.live = {**self.live, **deepcopy(payload)}
            return deepcopy(self.live)
        if endpoint == 'user':
            return {'login': 'appolon1908-hue'}
        if endpoint == PREFIX:
            assert method == 'GET'
            return {'default_branch': setup.BRANCH, 'permissions': {'admin': True}, 'allow_auto_merge': True}
        if endpoint == PROTECTION:
            assert method == 'GET'
            return deepcopy(self.classic)
        if endpoint == PROTECTION + '/required_pull_request_reviews':
            assert method == 'PATCH'
            self.classic['required_pull_request_reviews'].update(payload)
            return deepcopy(self.classic['required_pull_request_reviews'])
        if endpoint == f'{PREFIX}/rules/branches/{quote(setup.BRANCH, safe="")}?per_page=100':
            assert paged and method == 'GET'
            return [[]]
        if endpoint == f'{PREFIX}/git/ref/heads/{quote(setup.BRANCH, safe="")}':
            return {'object': {'sha': BASE}}
        if endpoint == f'{PREFIX}/pulls?state=open&per_page=100':
            assert paged and method == 'GET'
            return [[]]
        if endpoint == PR:
            assert method == 'GET'
            return {'state': 'closed' if self.merged else 'open', 'draft': False,
                    'head': {'sha': HEAD, 'repo': {'full_name': setup.REPO}},
                    'base': {'ref': setup.BRANCH}, 'merged': self.merged,
                    'merge_commit_sha': 'c' * 40 if self.merged else None}
        if endpoint == PR + '/merge':
            assert method == 'PUT'
            assert payload == {'sha': HEAD, 'merge_method': 'squash'}
            self.merged = True
            return {'merged': True}
        raise AssertionError(f'unexpected API call: {method} {endpoint}')


@pytest.fixture
def run_cutover(monkeypatch, tmp_path):
    def run(fake, *, apply=True):
        args = ['configure_checks_only_merge', '--bootstrap-pr', '317', '--expected-head', HEAD]
        monkeypatch.setattr(sys, 'argv', args + (['--apply'] if apply else []))
        monkeypatch.setattr(setup, 'api', fake)
        def verified(number, head, base):
            assert (number, head, base) == (317, HEAD, BASE)
            return 15368
        monkeypatch.setattr(setup, 'verify_candidate', verified)
        monkeypatch.setattr(setup.tempfile, 'mkdtemp', lambda **kwargs: str(tmp_path))
        return setup.main()
    return run


def add_requirement(live):
    checks = next(r['parameters']['required_status_checks'] for r in live['rules']
                  if r['type'] == 'required_status_checks')
    checks.append({'context': 'owner-added-security-check', 'integration_id': 15368})


def change_scope(live):
    live['conditions']['ref_name']['include'].append('refs/heads/owner-added-branch')


@pytest.mark.parametrize('classic', [True, False])
@pytest.mark.parametrize('edit', [add_requirement, change_scope, lambda r: r.update(name='owner-renamed-policy')])
def test_intervening_admin_edit_is_not_overwritten(run_cutover, capsys, tmp_path, classic, edit):
    fake = CutoverAPI(classic=classic, concurrent_edit=edit)
    assert run_cutover(fake) == 1
    assert fake.live == fake.concurrent_snapshot
    assert [c[1] for c in fake.calls if c[0] == RULESET].count('PUT') == 1
    assert not any(c[0] == PR + '/merge' for c in fake.calls)
    assert not fake.merged
    assert 'ruleset changed before final cutover' in capsys.readouterr().err
    assert (tmp_path / 'before.json').is_file()
    assert (tmp_path / 'desired-ruleset.json').is_file()
    assert not (tmp_path / 'after.json').exists()
    assert not (tmp_path / 'merge.json').exists()


@pytest.mark.parametrize('final_read', ['denied', 'malformed'])
def test_unavailable_final_read_does_not_lower_ruleset_reviews(run_cutover, tmp_path, final_read):
    fake = CutoverAPI(final_read=final_read)
    assert run_cutover(fake) == 1
    assert fake.reads == 4
    assert [c[1] for c in fake.calls if c[0] == RULESET].count('PUT') == 1
    params = next(r['parameters'] for r in fake.live['rules'] if r['type'] == 'pull_request')
    assert params['required_approving_review_count'] == 1
    assert not fake.merged
    assert not (tmp_path / 'after.json').exists()


@pytest.mark.parametrize('classic', [True, False])
def test_final_write_is_immediately_preceded_by_fresh_ruleset_read(run_cutover, tmp_path, classic):
    fake = CutoverAPI(classic=classic)
    assert run_cutover(fake) == 0
    writes = [i for i, call in enumerate(fake.calls) if call[:2] == (RULESET, 'PUT')]
    assert len(writes) == 2
    assert fake.calls[writes[-1] - 1] == (RULESET, 'GET', None)
    if classic:
        patch = next(i for i, call in enumerate(fake.calls) if call[1] == 'PATCH')
        assert patch < writes[-1] - 1
    assert fake.merged
    after = json.loads((tmp_path / 'after.json').read_text())
    assert setup.editable(after['ruleset']) == setup.policy_payload(initial_ruleset(), 15368, zero_reviews=True)
    assert after['classic_protection']['required_signatures'] == {'enabled': True}


def test_read_only_preflight_does_not_write_or_merge(run_cutover):
    fake = CutoverAPI()
    assert run_cutover(fake, apply=False) == 0
    assert all(c[1] == 'GET' for c in fake.calls)
    assert not fake.merged


def test_additional_applicable_review_rule_blocks_all_writes(monkeypatch, tmp_path):
    fake = CutoverAPI()
    def api(endpoint, method='GET', payload=None, paged=False):
        if '/rules/branches/' in endpoint:
            assert method == 'GET' and paged
            return [[{'type': 'pull_request', 'ruleset_id': setup.RULESET_ID + 1,
                      'parameters': {'required_approving_review_count': 1}}]]
        return fake(endpoint, method, payload, paged)
    monkeypatch.setattr(sys, 'argv', ['configure_checks_only_merge', '--bootstrap-pr', '317',
                                    '--expected-head', HEAD, '--apply'])
    monkeypatch.setattr(setup, 'api', api)
    monkeypatch.setattr(setup.tempfile, 'mkdtemp', lambda **kwargs: str(tmp_path))
    assert setup.main() == 1
    assert all(c[1] == 'GET' for c in fake.calls)
    assert not fake.merged
    assert not (tmp_path / 'before.json').exists()
