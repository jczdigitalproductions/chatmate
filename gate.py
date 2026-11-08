"""Verifier operator CLI. ACCEPT exits 0; BLOCK exits 1; configuration errors exit 2."""
import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv
from verifier import Store, generate_cases, object_json, public_report


def main(argv=None):
    load_dotenv(Path(__file__).with_name('.env'))
    parser = argparse.ArgumentParser(description='Chatmate independent verification gate')
    parser.add_argument('--state', type=Path, help='Operator-owned suite/key/evidence directory')
    commands = parser.add_subparsers(dest='command', required=True)
    propose = commands.add_parser('propose', help='Generate a test draft without receiving candidate source')
    propose.add_argument('requirements', type=Path, help='JSON with requirements, function, parameters')
    propose.add_argument('--output', type=Path, required=True)
    freeze = commands.add_parser('freeze', help='Approve and sign an operator-reviewed test contract/draft')
    freeze.add_argument('contract', type=Path)
    verify = commands.add_parser('verify', help='Verify one source file or file at an exact Git revision')
    verify.add_argument('--suite', required=True)
    verify.add_argument('--file', required=True)
    verify.add_argument('--repo', type=Path)
    verify.add_argument('--revision', help='Full immutable Git commit ID; requires --repo')
    verify.add_argument('--base', help='Full trusted base commit ID; required with --repo')
    replay = commands.add_parser('replay', help='Authenticate evidence and rerun its frozen suite')
    replay.add_argument('run_id')
    args = parser.parse_args(argv)
    try:
        if args.command == 'propose':
            spec = object_json(args.requirements.read_text(encoding='utf-8'))
            if set(spec) != {'requirements', 'function', 'parameters'}:
                raise ValueError('Blind author input must contain only requirements, function, parameters.')
            draft = generate_cases(**spec)
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(draft, stream, indent=2)
            print(f'Draft saved to {args.output}. Inspect expected outputs before freezing.')
            return 0
        store = Store(args.state)
        if args.command == 'freeze':
            draft = object_json(args.contract.read_text(encoding='utf-8'))
            contract = draft.get('contract', draft)
            print(store.freeze(contract, draft.get('provenance')))
            return 0
        if args.command == 'replay':
            report = store.replay(args.run_id)
        else:
            change = None
            if len({bool(args.repo), bool(args.revision), bool(args.base)}) != 1:
                raise ValueError('--repo, --base and --revision must be used together.')
            if args.repo:
                if not all(re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', value) for value in (args.base, args.revision)):
                    raise ValueError('Use full immutable Git commit IDs.')
                file = PurePosixPath(args.file)
                if file.is_absolute() or '..' in file.parts or ':' in args.file or '\\' in args.file:
                    raise ValueError('Use a repository-relative POSIX file path.')
                for revision in (args.base, args.revision):
                    kind = subprocess.run(['git', '-C', str(args.repo.resolve()), 'cat-file', '-t', revision],
                                          capture_output=True, timeout=15, check=True)
                    if kind.stdout.strip() != b'commit':
                        raise ValueError('Base and revision must identify commits.')
                changed = subprocess.run(['git', '-C', str(args.repo.resolve()), 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--name-only', '-z', args.base, args.revision],
                                         capture_output=True, timeout=15, check=True)
                if changed.stdout != args.file.encode('utf-8') + b'\0':
                    raise ValueError('The change must modify exactly the approved source file. Unverified file changes are blocked.')
                mode = subprocess.run(['git', '-C', str(args.repo.resolve()), 'ls-tree', '--format=%(objectmode) %(objecttype)', args.revision, '--', args.file],
                                      capture_output=True, timeout=15, check=True)
                if mode.stdout.strip() not in (b'100644 blob', b'100755 blob'):
                    raise ValueError('Candidate must be a regular source file, not a symlink or submodule.')
                result = subprocess.run(['git', '-C', str(args.repo.resolve()), 'show', '--no-ext-diff', '--no-textconv', f'{args.revision}:{args.file}'],
                                        capture_output=True, timeout=15, check=True)
                if len(result.stdout) > 100_000:
                    raise ValueError('Source is too large.')
                source = result.stdout.decode('utf-8')
                change = {'base': args.base, 'revision': args.revision, 'file': args.file,
                          'scope': 'Exactly one approved source file changed.'}
            else:
                source = Path(args.file).read_text(encoding='utf-8')
            report = store.verify(args.suite, source, args.revision, change)
        print(json.dumps(public_report(report), indent=2))
        return 0 if report['decision'] == 'ACCEPT' else 1
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'decision': 'BLOCK', 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
