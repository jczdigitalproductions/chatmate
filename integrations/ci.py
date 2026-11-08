"""Run from a TRUSTED base checkout; never import or checkout candidate code.

Publishes a commit status on the exact PR head; used by the example workflow.
"""
import base64
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gate import main
from verifier import object_json, Store


def run():
    event = object_json(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    pull = event['pull_request']
    head = pull['head']['sha']
    base = pull['base']['sha']
    repository = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository.')
    if not all(re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', value) for value in (head, base)):
        raise ValueError('Invalid immutable commit IDs.')
    status_url = f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{repository}/statuses/{head}"

    def status(state, description):
        request = Request(status_url, data=json.dumps({'state': state, 'context': 'chatmate/verifier',
            'description': description}).encode(), headers={
            'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
            'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
            'X-GitHub-Api-Version': '2026-03-10'})
        with urlopen(request, timeout=30) as response:
            response.read(10000)

    status('pending', 'Independent verifier running against this exact revision.')
    try:
        state_dir = Path(os.environ['RUNNER_TEMP']) / 'chatmate-state'
        state_dir.mkdir(exist_ok=True)
        key = base64.b64decode(os.environ['CHATMATE_SIGNING_KEY_B64'], validate=True)
        if len(key) != 32:
            raise ValueError('Invalid signing key.')
        (state_dir / 'signing.key').write_bytes(key)
        suite = object_json(base64.b64decode(os.environ['CHATMATE_SUITE_B64'], validate=True))
        suite_id = suite['suite_id']
        if not re.fullmatch('[0-9a-f]{64}', suite_id):
            raise ValueError('Invalid suite ID.')
        store = Store(state_dir)
        (state_dir / 'suites' / f'{suite_id}.json').write_text(json.dumps(suite), encoding='utf-8')
        store.load(suite_id)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(['--state', str(state_dir), 'verify', '--suite', suite_id,
                '--repo', os.environ['GITHUB_WORKSPACE'], '--base', base, '--revision', head,
                '--file', os.environ['CHATMATE_TARGET_FILE']])
        # Only public summaries are written to CI logs; vectors/key remain private.
        print(output.getvalue())
        status('success' if exit_code == 0 else 'failure',
               'ACCEPT: all frozen tests passed.' if exit_code == 0 else 'BLOCK: required verification did not pass.')
        return exit_code
    except Exception:
        status('failure', 'BLOCK: verifier could not complete required checks.')
        return 2


if __name__ == '__main__':
    raise SystemExit(run())
