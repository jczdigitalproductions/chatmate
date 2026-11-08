"""Reproducible offline demonstration, using explicitly operator-authored tests."""
import json
from pathlib import Path

from verifier import Store, object_json


def main():
    root = Path(__file__).parent
    store = Store()
    suite_id = store.freeze(object_json((root / 'demo' / 'contract.json').read_text(encoding='utf-8')))
    runs = {}
    for filename in ('defective', 'corrected', 'injection', 'escape'):
        report = store.verify(suite_id, (root / 'demo' / f'{filename}.py').read_text(encoding='utf-8'))
        runs[filename] = report
        print(f"{filename}: {report['decision']} ({report['passed']}/{report['total']} tests)")
    replay = store.replay(runs['corrected']['run_id'])
    assert [runs[n]['decision'] for n in ('defective', 'corrected', 'injection', 'escape')] == ['BLOCK', 'ACCEPT', 'BLOCK', 'BLOCK']
    assert replay['decision'] == 'ACCEPT'
    summary = {'suite_id': suite_id, 'runs': runs, 'replay': replay,
               'test_origin': 'operator-authored offline fixture, not a claimed live model generation'}
    (store.root / 'demo-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'Evidence saved in {store.root}; replay: ACCEPT')


if __name__ == '__main__':
    main()
