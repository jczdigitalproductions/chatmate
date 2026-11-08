const path = require('node:path');
const fs = require('node:fs');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const workspace = path.join(root, '.vscode-test', 'workspace');
fs.mkdirSync(workspace, {recursive: true});
const resultFile = path.join(root, '.vscode-test', 'host-result.json');
if (fs.existsSync(resultFile)) fs.unlinkSync(resultFile);
const launchArgs = [workspace, '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes', '--disable-gpu',
  '--user-data-dir=' + path.join(root, '.vscode-test', 'user-data'),
  '--extensions-dir=' + path.join(root, '.vscode-test', 'extensions')];
const env = {...process.env, CHATMATE_HOST_RESULT: resultFile};
delete env.ELECTRON_RUN_AS_NODE;
if (process.env.VSCODE_EXECUTABLE) {
  const child = spawn(process.env.VSCODE_EXECUTABLE, [...launchArgs,
    '--extensionDevelopmentPath=' + root, '--extensionTestsPath=' + path.join(__dirname, 'host.cjs')],
    {env, stdio: 'inherit', windowsHide: true});
  const timer = setTimeout(() => {child.kill(); console.error('VS Code host test timed out.'); process.exitCode = 1;}, 60000);
  child.on('error', error => {clearTimeout(timer); console.error(error.message); process.exitCode = 1;});
  child.on('exit', code => {
    clearTimeout(timer);
    let result;
    try {result = JSON.parse(fs.readFileSync(resultFile, 'utf8'));} catch {}
    if (code !== 0 || result?.status !== 'passed') {console.error(result || 'No successful host-test receipt.'); process.exitCode = 1;}
    else console.log(result.message);
  });
} else {
  const {runTests} = require('@vscode/test-electron');
  runTests({extensionDevelopmentPath: root, extensionTestsPath: path.join(__dirname, 'host.cjs'),
    extensionTestsEnv: {CHATMATE_HOST_RESULT: resultFile}, launchArgs,
  }).catch(error => {console.error(error.message); process.exitCode = 1;});
}
