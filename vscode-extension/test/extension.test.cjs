const {test} = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const core = require('../src/core');

function setup(source = 'def add(a, b):\n    return a + b', languageId = 'python') {
  const commands = new Map(), events = {}, secrets = new Map(), state = new Map([['suiteId', 'a'.repeat(64)]]);
  const collections = [], messages = [], writes = [], posts = [];
  const dispose = () => ({dispose() {}});
  const uri = value => ({toString: () => value});
  const doc = {languageId, version: 1, uri: uri('file:///candidate.py'), getText: () => source};
  const config = {inspect: name => ({globalValue: name === 'transport' ? 'direct' : undefined,
    workspaceValue: name === 'verifierUrl' ? 'https://attacker.example' : undefined}), update: async () => {}};
  const vs = {
    Uri: {joinPath: (base, ...parts) => uri(base.toString() + '/' + parts.join('/'))},
    StatusBarAlignment: {Left: 1}, ConfigurationTarget: {Global: 1}, ProgressLocation: {Notification: 1},
    DiagnosticSeverity: {Error: 0, Warning: 1, Information: 2},
    Range: class {constructor(...args) {this.args = args;}}, Diagnostic: class {constructor(range, message, severity) {Object.assign(this, {range, message, severity});}},
    languages: {createDiagnosticCollection: () => {const items = new Map(); const c = {items, set: (u, ds) => items.set(u.toString(), ds), delete: u => items.delete(u.toString()), clear: () => items.clear(), dispose() {}}; collections.push(c); return c;}},
    commands: {registerCommand: (id, handler) => {commands.set(id, handler); return dispose();}, executeCommand: async (id, ...args) => commands.get(id)?.(...args)},
    workspace: {isTrusted: true, getConfiguration: () => config,
      onDidChangeTextDocument: cb => {events.change = cb; return dispose();},
      onDidChangeConfiguration: cb => {events.config = cb; return dispose();},
      fs: {createDirectory: async () => {}, writeFile: async (u, data) => writes.push([u.toString(), data.toString()])},
      openTextDocument: async options => ({...doc, languageId: options.language, getText: () => options.content})},
    window: {activeTextEditor: {document: doc},
      createStatusBarItem: () => ({show() {}, dispose() {}}),
      showErrorMessage: async message => {messages.push(message);}, showInformationMessage: async message => {messages.push(message);},
      showWarningMessage: async () => 'Freeze reviewed suite', showInputBox: async () => undefined,
      showTextDocument: async opened => {vs.window.activeTextEditor = {document: opened};},
      onDidChangeActiveTextEditor: cb => {events.editor = cb; return dispose();},
      withProgress: async (_opts, callback) => callback({}, {onCancellationRequested: dispose}),
      registerWebviewViewProvider: (_id, p) => {events.provider = p; return dispose();}}
  };
  const context = {subscriptions: [], extensionUri: uri('file:///extension'), globalStorageUri: uri('file:///private'),
    secrets: {get: async name => secrets.get(name), store: async (name, value) => secrets.set(name, value), delete: async name => secrets.delete(name)},
    workspaceState: {get: (name, fallback) => state.get(name) ?? fallback, update: async (name, value) => state.set(name, value)}};
  const originalLoad = Module._load;
  Module._load = function(request, ...args) {return request === 'vscode' ? vs : originalLoad.call(this, request, ...args);};
  delete require.cache[require.resolve('../src/extension')];
  let extension;
  try {extension = require('../src/extension');} finally {Module._load = originalLoad;}
  const api = extension.activate(context);
  const webview = {cspSource: 'test-resource:', asWebviewUri: u => u.toString(), postMessage: message => posts.push(message),
    onDidReceiveMessage: cb => {events.message = cb; return dispose();}};
  events.provider.resolveWebviewView({webview});
  return {vs, context, commands, secrets, state, events, doc, api, collections, messages, writes, posts, webview,
    edit(value) {source = value; doc.version += 1; events.change({document: doc});}};
}
function goodReport(source) {return {decision: 'ACCEPT', suite_id: 'a'.repeat(64), source_sha256: core.hash(source), run_id: 'b'.repeat(64),
  total: 12, passed: 12, reasons: [], engine: 'chatmate-integer-v1', policy: {version: 'chatmate-gate-v2', required_pass_rate: 1, unsupported: 'BLOCK', missing_evidence: 'BLOCK', minimum_cases: 6, maximum_cases: 100, ai_review_is_gate: false}};}

test('verification ignores workspace endpoint overrides and never sends secrets to sidebar', async () => {
  const s = setup();
  s.secrets.set('CHATMATE_SUBMIT_TOKEN', 'private-submit-token');
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {assert.equal(url, 'http://127.0.0.1:5050/api/verify'); assert.equal(options.headers.Authorization, 'Bearer private-submit-token'); return new Response(JSON.stringify(goodReport(s.doc.getText())));};
  try {await s.commands.get('chatmate.verify')();} finally {globalThis.fetch = originalFetch;}
  assert.equal(s.api.getState().last.report.decision, 'ACCEPT');
  assert.equal(s.writes.length, 1);
  assert.ok(!JSON.stringify(s.posts).includes('private-submit-token'));
  assert.ok(s.webview.html.includes("connect-src 'none'"));
});
test('editing after acceptance invalidates the previous verdict', async () => {
  const s = setup();
  s.secrets.set('CHATMATE_SUBMIT_TOKEN', 'key');
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify(goodReport(s.doc.getText())));
  try {await s.commands.get('chatmate.verify')();} finally {globalThis.fetch = originalFetch;}
  s.edit('def add(a, b):\n    return a - b');
  assert.equal(s.api.getState().last.freshness, 'stale');
  assert.ok(s.api.getState().summary.includes('BLOCK'));
  assert.equal(s.collections[0].items.get(s.doc.uri.toString())[0].severity, 0);
});
test('source changes during a response cannot receive a current ACCEPT', async () => {
  const s = setup(); s.secrets.set('CHATMATE_SUBMIT_TOKEN', 'key');
  const oldSource = s.doc.getText();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {s.edit('def add(a, b):\n    return 0'); return new Response(JSON.stringify(goodReport(oldSource)));};
  try {await s.commands.get('chatmate.verify')();} finally {globalThis.fetch = originalFetch;}
  assert.equal(s.api.getState().last.freshness, 'stale');
});
test('verification outage creates BLOCK and no saved acceptance artifact', async () => {
  const s = setup(); s.secrets.set('CHATMATE_SUBMIT_TOKEN', 'key');
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {throw new Error('offline');};
  try {await s.commands.get('chatmate.verify')();} finally {globalThis.fetch = originalFetch;}
  assert.equal(s.api.getState().last.report.decision, 'BLOCK');
  assert.equal(s.api.getState().last.freshness, 'incomplete');
  assert.equal(s.writes.length, 0);
});
test('untrusted workspace cannot submit code or prompt for credentials', async () => {
  const s = setup(); s.vs.workspace.isTrusted = false;
  await s.commands.get('chatmate.verify')();
  assert.equal(s.api.getState().last, undefined);
  assert.ok(s.messages[0].includes('Trust the workspace'));
});
test('sidebar cannot execute arbitrary VS Code commands', () => {
  const s = setup();
  let called = false;
  s.vs.commands.executeCommand = () => {called = true;};
  s.events.message({type: 'command', command: 'workbench.action.terminal.new'});
  s.events.message({type: 'command', command: 'crossReview', question: {malicious: true}});
  assert.equal(called, false);
});
