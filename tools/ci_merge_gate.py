#!/usr/bin/env python3
"""Read-only, fail-closed aggregation of current PR CI; never approve or merge."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from urllib.parse import quote

REQUIRED_WORKFLOWS = {
    '.github/workflows/platform-source-gate.yml',
    '.github/workflows/gitleaks-pr-diagnostics.yml',
}
REQUIRED_CHECKS = {'validate', 'diagnose'}
SELF_CHECKS = {'production-gate', 'checks-only-policy'}
SELF_WORKFLOW = '.github/workflows/production-merge-gate.yml'


def gh_json(endpoint: str, *, paged: bool = False):
    command = ['gh', 'api', '--method', 'GET', endpoint]
    if paged:
        command += ['--paginate', '--slurp']
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    return json.loads(result.stdout)


def latest(rows: list[dict], keys) -> list[dict]:
    found = {}
    for row in rows:
        key = keys(row)
        rank = (int(row.get('id', 0)), int(row.get('run_attempt', 0)))
        if key not in found or rank > found[key][0]:
            found[key] = (rank, row)
    return [item[1] for item in found.values()]


def evaluate(snapshot: dict) -> dict:
    """Missing evidence stays pending; a failed/invalid mandatory job never passes."""
    failures, pending = [], []
    checks = snapshot['checks']
    statuses = latest(snapshot['statuses'], lambda row: (row.get('sha'), row['context']))
    runs = latest(snapshot['runs'], lambda row: row['workflow_id'])
    for name in sorted(REQUIRED_CHECKS):
        observed = [row for row in checks if row.get('name') == name
                    and row.get('app', {}).get('slug') == 'github-actions']
        if not observed:
            pending.append(f'missing mandatory check: {name}')
    for path in sorted(REQUIRED_WORKFLOWS):
        observed = [row for row in runs if row.get('path', '').split('@')[0] == path]
        if not observed:
            pending.append(f'missing mandatory workflow: {path}')
    for row in checks:
        name = row['name']
        app = row.get('app', {}).get('slug')
        if name in SELF_CHECKS and app == 'github-actions':
            continue
        if row.get('status') != 'completed':
            pending.append(f'check running: {name}')
            continue
        permitted = {'success'} if name in REQUIRED_CHECKS else {'success', 'skipped', 'neutral'}
        if row.get('conclusion') not in permitted:
            failures.append(f'check {name}: {row.get("conclusion")}')
    for row in statuses:
        state, name = row.get('state'), row['context']
        if state == 'pending':
            pending.append(f'status pending: {name}')
        elif state != 'success':
            failures.append(f'status {name}: {state}')
    for row in runs:
        path = row.get('path', '').split('@')[0]
        if path == SELF_WORKFLOW:
            continue
        if row.get('status') != 'completed':
            pending.append(f'workflow running: {path}')
            continue
        permitted = {'success'} if path in REQUIRED_WORKFLOWS else {'success', 'skipped', 'neutral'}
        if row.get('conclusion') not in permitted:
            failures.append(f'workflow {path}: {row.get("conclusion")}')
    return {'state': 'failure' if failures else 'pending' if pending else 'success',
            'failures': sorted(set(failures)), 'pending': sorted(set(pending))}


def collect(repo: str, number: int, head: str, base: str) -> dict:
    prefix = f'repos/{repo}'
    pr = gh_json(f'{prefix}/pulls/{number}')
    if pr['state'] != 'open' or pr['head']['sha'] != head:
        raise ValueError('PR closed or head changed; rerun for the new candidate')
    current_base = gh_json(f'{prefix}/git/ref/heads/{quote(pr["base"]["ref"], safe="")}')['object']['sha']
    if current_base != base:
        raise ValueError('target branch advanced; integrate the new base and rerun CI')
    # Head contains the tested target, so checks cannot pass for a stale integration.
    comparison = gh_json(f'{prefix}/compare/{base}...{head}')
    if comparison.get('behind_by') != 0:
        raise ValueError('PR branch is behind its target; update it before merging')
    shas = [head]
    merge_sha = pr.get('merge_commit_sha')
    if pr.get('mergeable') is False:
        raise ValueError('PR has merge conflicts')
    if merge_sha and merge_sha != head:
        commit = gh_json(f'{prefix}/git/commits/{merge_sha}')
        if {parent['sha'] for parent in commit['parents']} != {base, head}:
            raise ValueError('test-merge identity changed; rerun CI')
        shas.append(merge_sha)
    checks, statuses = [], []
    for sha in shas:
        pages = gh_json(f'{prefix}/commits/{sha}/check-runs?per_page=100&filter=latest', paged=True)
        for page in pages:
            checks.extend(page['check_runs'])
        pages = gh_json(f'{prefix}/commits/{sha}/statuses?per_page=100', paged=True)
        for page in pages:
            statuses.extend({**row, 'sha': sha} for row in page)
    # Status identity includes SHA, so a new merge's pending/failure cannot be
    # hidden by an older head's successful context of the same name.
    statuses = latest(statuses, lambda row: (row.get('sha'), row['context']))
    pages = gh_json(f'{prefix}/actions/runs?event=pull_request&head_sha={head}&per_page=100', paged=True)
    runs = [run for page in pages for run in page['workflow_runs']
            if run.get('head_sha') == head and run.get('event') == 'pull_request'
            and (not run.get('pull_requests') or any(p['number'] == number for p in run['pull_requests']))]
    return {'checks': checks, 'statuses': statuses, 'runs': runs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        parser.error('invalid repository')
    if args.pr <= 0 or any(not re.fullmatch(r'[0-9a-f]{40}', sha) for sha in (args.head, args.base)):
        parser.error('invalid PR or commit SHA')
    deadline = time.monotonic() + 1800
    time.sleep(60)  # Allow sibling workflows to register, without accepting absence.
    previous = None
    while time.monotonic() < deadline:
        try:
            snapshot = collect(args.repo, args.pr, args.head, args.base)
            verdict = evaluate(snapshot)
        except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
            print('CI_MERGE_GATE=FAIL: unavailable, stale, or malformed GitHub evidence')
            return 1
        print(json.dumps(verdict, sort_keys=True), flush=True)
        if verdict['state'] == 'failure':
            return 1
        stable = json.dumps(snapshot, sort_keys=True)
        if verdict['state'] == 'success' and stable == previous:
            print('CI_MERGE_GATE=PASS')
            return 0
        previous = stable if verdict['state'] == 'success' else None
        time.sleep(20)
    print('CI_MERGE_GATE=FAIL: timed out waiting for mandatory successful evidence')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
