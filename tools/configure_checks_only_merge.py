#!/usr/bin/env python3
"""Owner-side policy cutover. Read-only unless --apply; no credentials in source.

Run only from the reviewed bootstrap checkout with the owner's existing gh
session. This does not grant a ChatGPT connector administration permissions.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

try:
    from . import ci_merge_gate as gate
except ImportError:
    import ci_merge_gate as gate

REPO = 'appolon1908-hue/codestra-production-platform'
BRANCH = 'release/production-activation'
RULESET_ID = 22197395
REQUIRED = {'validate', 'diagnose', 'production-gate', 'checks-only-policy'}
CI_FILES = (
    '.github/workflows/platform-source-gate.yml',
    '.github/workflows/gitleaks-pr-diagnostics.yml',
    '.github/workflows/production-merge-gate.yml',
    'tools/ci_merge_gate.py',
)
REVIEW_PATCH = {
    'required_approving_review_count': 0,
    'dismiss_stale_reviews': False,
    'require_code_owner_reviews': False,
    'require_last_push_approval': False,
}


def api(endpoint, method='GET', payload=None, paged=False):
    command = ['gh', 'api', '--method', method, '-H', 'Accept: application/vnd.github+json', endpoint]
    if payload is not None:
        command += ['--input', '-']
    if paged:
        command += ['--paginate', '--slurp']
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            check=True, capture_output=True, text=True, timeout=60)
    return json.loads(result.stdout) if result.stdout.strip() else None


def editable(record):
    value = {key: copy.deepcopy(record[key]) for key in
             ('name', 'target', 'enforcement', 'conditions', 'bypass_actors', 'rules')}
    value['rules'].sort(key=lambda rule: rule['type'])
    for rule in value['rules']:
        if rule['type'] == 'required_status_checks':
            rule['parameters']['required_status_checks'].sort(key=lambda row: row['context'])
    return value


def policy_payload(record: dict, actions_app_id: int, *, zero_reviews: bool) -> dict:
    if record['id'] != RULESET_ID or record['source'] != REPO or record['target'] != 'branch':
        raise ValueError('unexpected ruleset identity')
    if record['enforcement'] != 'active' or record.get('bypass_actors'):
        raise ValueError('inactive ruleset or unexpected bypass; manual owner review required')
    if record['conditions'] != {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}}:
        raise ValueError('unexpected branch scope; refusing to change another branch')
    if type(actions_app_id) is not int or actions_app_id <= 0:
        raise ValueError('missing verified GitHub Actions identity')
    payload = editable(record)
    rules = payload['rules']
    pr_rules = [r for r in rules if r['type'] == 'pull_request']
    if len(pr_rules) != 1:
        raise ValueError('ambiguous pull-request rule')
    params = pr_rules[0]['parameters']
    if zero_reviews:
        params.update(required_approving_review_count=0,
                      dismiss_stale_reviews_on_push=False,
                      require_code_owner_review=False,
                      require_last_push_approval=False,
                      require_extra_approval_for_unattributed_changes=False)
        if 'required_reviewers' in params:
            params['required_reviewers'] = []
    params['required_review_thread_resolution'] = True
    params['allowed_merge_methods'] = ['squash']
    for kind in ('deletion', 'non_fast_forward', 'required_linear_history', 'required_signatures'):
        if not any(rule['type'] == kind for rule in rules):
            rules.append({'type': kind})
    checks = [rule for rule in rules if rule['type'] == 'required_status_checks']
    if len(checks) > 1:
        raise ValueError('ambiguous required-check rule')
    if not checks:
        checks = [{'type': 'required_status_checks', 'parameters': {'required_status_checks': []}}]
        rules.append(checks[0])
    params = checks[0]['parameters']
    params['strict_required_status_checks_policy'] = True
    params['do_not_enforce_on_create'] = False
    # Preserve every pre-existing requirement and its expected source.
    existing = params['required_status_checks']
    for context in sorted(REQUIRED):
        matching = [row for row in existing if row['context'] == context]
        if matching and any(row.get('integration_id') not in (None, actions_app_id) for row in matching):
            raise ValueError('existing check is bound to a different app')
        if matching:
            for row in matching:
                row['integration_id'] = actions_app_id
        else:
            existing.append({'context': context, 'integration_id': actions_app_id})
    return editable(payload)


def verify_candidate(number: int, head: str, base: str) -> int:
    root = Path(__file__).resolve().parents[1]
    for filename in CI_FILES:
        resource = api(f'repos/{REPO}/contents/{filename}?ref={head}')
        remote = base64.b64decode(resource['content'])
        if hashlib.sha256(remote).digest() != hashlib.sha256((root / filename).read_bytes()).digest():
            raise ValueError(f'candidate differs from this reviewed checkout: {filename}')
    snapshot = gate.collect(REPO, number, head, base)
    if gate.evaluate(snapshot)['state'] != 'success':
        raise ValueError('bootstrap CI has not fully succeeded')
    apps = set()
    for name in REQUIRED:
        observed = [check for check in snapshot['checks']
                    if check.get('name') == name and check.get('app', {}).get('slug') == 'github-actions']
        if not observed or any(c.get('status') != 'completed' or c.get('conclusion') != 'success' for c in observed):
            raise ValueError(f'mandatory successful check missing: {name}')
        apps.update(c['app']['id'] for c in observed)
    if len(apps) != 1:
        raise ValueError('ambiguous CI publisher')
    return apps.pop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap-pr', required=True, type=int)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--apply', action='store_true', help='Apply the authorized policy and normally squash-merge only the bootstrap PR')
    args = parser.parse_args()
    if args.bootstrap_pr <= 0 or not re.fullmatch(r'[0-9a-f]{40}', args.expected_head):
        parser.error('invalid bootstrap PR or expected SHA')
    prefix = f'repos/{REPO}'
    protection_path = f'{prefix}/branches/{quote(BRANCH, safe="")}/protection'
    evidence = None
    try:
        viewer = api('user')['login']
        if viewer != REPO.split('/')[0]:
            raise ValueError('use appolon1908-hue owner session, not another reviewer identity')
        repository = api(prefix)
        if repository['default_branch'] != BRANCH or not repository.get('permissions', {}).get('admin'):
            raise ValueError('expected repository owner administration permission and target branch')
        record = api(f'{prefix}/rulesets/{RULESET_ID}')
        # A denied protection read is fatal: never substitute a fabricated snapshot.
        protection = api(protection_path)
        applied = [r for page in api(f'{prefix}/rules/branches/{quote(BRANCH, safe="")}?per_page=100', paged=True) for p in [] for r in p]
        for rule in applied:
            if rule['type'] == 'pull_request' and rule.get('ruleset_id') != RULESET_ID:
                p = rule['parameters']
                if p.get('required_approving_review_count', 0) or p.get('require_code_owner_review') or p.get('require_last_push_approval') or p.get('required_reviewers'):
                    raise ValueError('another applicable review rule needs explicit reconciliation')
        pr = api(f'{prefix}/pulls/{args.bootstrap_pr}')
        if pr['state'] != 'open' or pr.get('draft') or pr['head']['sha'] != args.expected_head or pr['base']['ref'] != BRANCH or pr['head']['repo']['full_name'] != REPO:
            raise ValueError('bootstrap PR is not the exact open, non-draft same-repository candidate')
        base = api(f'{prefix}/git/ref/heads/{quote(BRANCH, safe="")}')['object']['sha']
        app_id = verify_candidate(args.bootstrap_pr, args.expected_head, base)
        strengthened = policy_payload(record, app_id, zero_reviews=False)
        desired = policy_payload(record, app_id, zero_reviews=True)
        open_prs = [p for page in api(f'{prefix}/pulls?state=open&per_page=100', paged=True) for p in page]
        evidence = Path(tempfile.mkdtemp(prefix='codestra-checks-only-policy-'))
        before = {'repository': repository, 'ruleset': record, 'classic_protection': protection,
                  'applicable_rules': applied, 'base': base,
                  'bootstrap_pr': args.bootstrap_pr, 'expected_head': args.expected_head,
                  'auto_merge_prs': [p['number'] for p in open_prs if p.get('auto_merge')]}
        (evidence / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
        (evidence / 'desired-ruleset.json').write_text(json.dumps(desired, indent=2) + '\n')
        print(f'EVIDENCE_DIRECTORY={evidence}')
        if not args.apply:
            print('MODE=READ_ONLY; live review requirement not changed')
            return 0
        # Guard against concurrent policy edits before the first write.
        if editable(api(f'{prefix}/rulesets/{RULESET_ID}')) != editable(record):
            raise ValueError('ruleset changed during preflight')
        # First enforce new contexts while retaining the old review requirement.
        # Old queued heads lack checks-only-policy and cannot race the cutover.
        api(f'{prefix}/rulesets/{RULESET_ID}', 'PUT', strengthened)
        if editable(api(f'{prefix}/rulesets/{RULESET_ID}')) != strengthened:
            raise ValueError('strengthened policy readback differs; zero-review cutover not attempted')
        reviews = protection.get('required_pull_request_reviews')
        if reviews is not None:
            api(protection_path + '/required_pull_request_reviews', 'PATCH', REVIEW_PATCH)
        # The earlier readback predates classic-protection reconciliation.
        # Refuse to overwrite an administrator's intervening edit with desired,
        # which was derived from the original preflight snapshot. Do not retry
        # or roll back over that edit. This GET/PUT pair is not an atomic lock;
        # the owner must keep other policy writers paused for the cutover.
        if editable(api(f'{prefix}/rulesets/{RULESET_ID}')) != strengthened:
            raise ValueError('ruleset changed before final cutover; concurrent policy preserved')
        api(f'{prefix}/rulesets/{RULESET_ID}', 'PUT', desired)
        after = api(f'{prefix}/rulesets/{RULESET_ID}')
        classic_after = api(protection_path)
        if editable(after) != desired:
            raise ValueError('final ruleset readback differs')
        for key, value in protection.items():
            if key != 'required_pull_request_reviews' and classic_after.get(key) != value:
                raise ValueError(f'unrelated classic protection changed: {key}')
        if reviews is not None and any(classic_after['required_pull_request_reviews'].get(k) != v for k, v in REVIEW_PATCH.items()):
            raise ValueError('classic review requirement remains')
        if not repository.get('allow_auto_merge'):
            api(prefix, 'PATCH', {'allow_auto_merge': True})
        (evidence / 'after.json').write_text(json.dumps({'ruleset': after, 'classic_protection': classic_after}, indent=2) + '\n')
        print('LIVE_REVIEW_REQUIREMENT=0; REQUIRED_CHECKS=' + ','.join(sorted(REQUIRED)))
        # Normal endpoint only; do not dismiss reviews or bypass a rejection.
        latest_pr = api(f'{prefix}/pulls/{args.bootstrap_pr}')
        if not latest_pr.get('merged'):
            result = api(f'{prefix}/pulls/{args.bootstrap_pr}/merge', 'PUT',
                         {'sha': args.expected_head, 'merge_method': 'squash'})
            if not result.get('merged'):
                raise ValueError('policy changed but normal bootstrap merge remains blocked')
        confirmed = api(f'{prefix}/pulls/{args.bootstrap_pr}')
        if not confirmed.get('merged'):
            raise ValueError('bootstrap merge not confirmed')
        (evidence / 'merge.json').write_text(json.dumps(confirmed, indent=2) + '\n')
        print('BOOTSTRAP_MERGE_SHA=' + confirmed['merge_commit_sha'])
        print('DEPLOYMENT_REQUESTED=NO; REVIEW_IDENTITY_IMPERSONATION=NO')
        return 0
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            # Do not print API response bodies or authentication material.
            print('BLOCKED: owner gh command rejected or could not read/write repository administration', file=sys.stderr)
        else:
            print(f'BLOCKED: {exc}', file=sys.stderr)
        if evidence:
            print(f'Inspect snapshots at {evidence}; changes may be partial. Do not bypass checks.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
