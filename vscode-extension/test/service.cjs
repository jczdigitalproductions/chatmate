// Optional real local HTTP check: no provider keys or model requests.
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../src/core');
const root = path.resolve(__dirname, '..');
const directory = path.join(root, '.vscode-test');
fs.mkdirSync(directory, {recursive: true});
const state = fs.mkdtempSync(path.join(directory, 'service-state-'));
const operator = 'test-operator-credential-for-local-run-123';
const submitter = 'test-submit-credential-for-local-run-123';
const server = spawn(process.env.PYTHON || 'python', ['-c', "from app import app; app.run(host='127.0.0.1', port=5053, debug=False)"], {
  cwd: path.resolve(root, '..'), windowsHide: true,
  env: {...process.env, CHATMATE_STATE_DIR: state, CHATMATE_OPERATOR_TOKEN: operator, CHATMATE_SUBMIT_TOKEN: submitter,
    META_MODEL_API_KEY: '', MODEL_API_KEY: '', AGENTVERSE_API_KEY: ''}
});
(async () => {
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Local verifier did not start.')), 10000);
      server.on('error', e => {clearTimeout(timer); reject(e);});
      server.on('exit', () => {clearTimeout(timer); reject(new Error('Local verifier exited early.'));});
      server.stderr.on('data', data => {if (String(data).includes('Running on')) {clearTimeout(timer); resolve();}});
    });
    const suite = await core.requestJson('http://127.0.0.1:5053/api/suites/demo', {secret: operator, body: {}});
    for (const [file, decision] of [['defective.py', 'BLOCK'], ['corrected.py', 'ACCEPT'], ['injection.py', 'BLOCK'], ['escape.py', 'BLOCK']]) {
      const source = fs.readFileSync(path.resolve(root, '..', 'demo', file), 'utf8');
      const result = await core.requestJson('http://127.0.0.1:5053/api/verify', {secret: submitter, body: {suite_id: suite.suite_id, code: source}});
      core.validateReport(result, source, suite.suite_id);
      if (result.decision !== decision) throw new Error('Unexpected decision for ' + file);
    }
    console.log('Real service/client check passed: suite freeze, source hashes, BLOCK/ACCEPT, injection and escape.');
  } finally {server.kill();}
})().catch(error => {console.error(error.message); process.exitCode = 1;});
