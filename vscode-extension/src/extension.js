'use strict';
const vscode = require('vscode');
const {randomBytes} = require('node:crypto');
const core = require('./core');

const SECRET_NAMES = ['ASI_ONE_API_KEY', 'CHATMATE_SUBMIT_TOKEN', 'CHATMATE_OPERATOR_TOKEN'];
const COMMANDS = ['open', 'configureConnection', 'configureSecret', 'newRequirements', 'generateTests',
  'freezeSuite', 'selectSuite', 'demoSuite', 'verify', 'crossReview', 'showReport'];

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection('Chatmate gate');
  const advisory = vscode.languages.createDiagnosticCollection('Chatmate Meta advisory');
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.command = 'chatmate.open';
  status.tooltip = 'Independent verification precheck. Required CI enforces merges.';
  context.subscriptions.push(diagnostics, advisory, status);
  let last;
  let view;
  let busy = false;
  let summary = 'Ready · no candidate verified';

  // Ignore workspace overrides for destinations/models, even in a trusted workspace.
  function setting(name, fallback) {
    const inspected = vscode.workspace.getConfiguration('chatmate').inspect(name);
    return inspected?.globalValue ?? fallback;
  }
  function origin() { return core.validateOrigin(setting('verifierUrl', 'http://127.0.0.1:5050')); }
  function publish() {
    const doc = vscode.window.activeTextEditor?.document;
    if (last?.freshness === 'current' && doc?.uri.toString() === last.source_uri
      && core.hash(doc.getText()) !== last.source_sha256) {
      last.freshness = 'stale';
      summary = 'STALE / BLOCK: the current file differs from the verified source. Verify again.';
      markBlocked(doc, 'The current file differs from the verified source.');
    }
    const fresh = last?.kind === 'verification' && last.freshness === 'current'
      && doc?.uri.toString() === last.source_uri && core.hash(doc.getText()) === last.source_sha256;
    status.text = busy ? '$(sync~spin) Chatmate: checking' : fresh
      ? `$(shield) Chatmate: ${last.report.decision}` : '$(shield) Chatmate: unverified';
    status.show();
    if (view) void view.webview.postMessage({type: 'state', busy, summary,
      suite: context.workspaceState.get('suiteId', ''), report: last || null});
  }
  async function credential(name) {
    let secret = await context.secrets.get(name);
    if (!secret) {
      secret = await vscode.window.showInputBox({title: `Store ${name}`, password: true, ignoreFocusOut: true,
        prompt: 'Saved in VS Code SecretStorage. Never written to project files.',
        validateInput: value => value.trim() ? undefined : 'Enter a credential.'});
      if (!secret) throw new Error(`Missing ${name}; operation canceled.`);
      await context.secrets.store(name, secret);
    }
    return secret;
  }
  async function service(path, body, role, signal) {
    const base = origin();
    const secret = await credential(role === 'operator' ? 'CHATMATE_OPERATOR_TOKEN' : 'CHATMATE_SUBMIT_TOKEN');
    return core.requestJson(base + path, {secret, body, signal});
  }
  function document(language) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) throw new Error('Open the document you want to use.');
    if (language && editor.document.languageId !== language) throw new Error(`Open a ${language} document first.`);
    const source = editor.document.getText();
    if (!source.trim() || source.length > 50000) throw new Error('The active document must contain 1–50000 characters.');
    return {doc: editor.document, source, version: editor.document.version, sourceHash: core.hash(source)};
  }
  async function jsonDocument(value) {
    const doc = await vscode.workspace.openTextDocument({language: 'json', content: JSON.stringify(value, null, 2)});
    await vscode.window.showTextDocument(doc);
  }
  function markBlocked(doc, message) {
    const diagnostic = new vscode.Diagnostic(new vscode.Range(0, 0, 0, 0), message, vscode.DiagnosticSeverity.Error);
    diagnostic.source = 'Chatmate gate';
    diagnostics.set(doc.uri, [diagnostic]);
  }
  async function progress(title, action) {
    return vscode.window.withProgress({location: vscode.ProgressLocation.Notification, title, cancellable: true},
      async (_progress, token) => {
        const controller = new AbortController();
        if (token.isCancellationRequested) controller.abort();
        const listener = token.onCancellationRequested(() => controller.abort());
        try { return await action(controller.signal); }
        finally { listener.dispose(); }
      });
  }
  const handlers = {
    open: () => vscode.commands.executeCommand('chatmate.panel.focus'),
    async configureConnection() {
      const value = await vscode.window.showInputBox({title: 'Trusted verifier service', value: origin(),
        prompt: 'The selected service receives candidate source. Use HTTPS except on loopback.',
        validateInput: input => {try {core.validateOrigin(input); return undefined;} catch (e) {return e.message;}}});
      if (!value) return;
      const transport = await vscode.window.showQuickPick([
        {label: 'Direct verifier service', value: 'direct'},
        {label: 'Agentverse through trusted gateway', value: 'agentverse'}
      ], {title: 'Verification transport'});
      if (!transport) return;
      const config = vscode.workspace.getConfiguration('chatmate');
      await config.update('verifierUrl', core.validateOrigin(value), vscode.ConfigurationTarget.Global);
      await config.update('transport', transport.value, vscode.ConfigurationTarget.Global);
      summary = 'Connection configured. Store a separate submission credential.';
    },
    async configureSecret() {
      const name = await vscode.window.showQuickPick(SECRET_NAMES, {title: 'Credential to store or remove'});
      if (!name) return;
      const action = await vscode.window.showQuickPick(['Store / replace', 'Remove'], {title: name});
      if (!action) return;
      if (action === 'Remove') await context.secrets.delete(name);
      else {
        const value = await vscode.window.showInputBox({title: `Store ${name}`, password: true, ignoreFocusOut: true,
          prompt: 'SecretStorage only. Agentverse and Meta keys belong on the verifier service.'});
        if (!value?.trim()) return;
        await context.secrets.store(name, value);
      }
      summary = 'Credential updated. Its value is never sent to the sidebar.';
    },
    async newRequirements() {
      await jsonDocument({requirements: 'Implement add(a, b) for integer inputs from -1000000000 to 1000000000 inclusive. Return their integer sum, including negatives and zero.',
        function: 'add', parameters: ['a', 'b']});
      summary = 'Write the behavior contract before generating tests. Candidate code is not read by this step.';
    },
    async generateTests() {
      const {source} = document('json');
      let spec;
      try {spec = JSON.parse(source);} catch {throw new Error('Open a valid requirements JSON document.');}
      core.validateSpec(spec);
      const key = await credential('ASI_ONE_API_KEY');
      const draft = await progress('Chatmate: ASI:One is drafting requirements-only tests',
        signal => core.generateBlindDraft(spec, key, {model: setting('asiModel', 'asi1'), signal}));
      await jsonDocument(draft);
      summary = 'Blind test draft ready. Review expected results before freezing. No candidate source was sent to ASI:One.';
    },
    async freezeSuite() {
      if (setting('transport', 'direct') === 'agentverse') throw new Error('Freeze tests directly on the remote verifier service as its operator, then select that suite ID for Agentverse verification.');
      let draft;
      try {draft = JSON.parse(document('json').source);} catch {throw new Error('Open a valid test draft JSON document.');}
      if (!draft || Object.keys(draft).sort().join('|') !== 'contract|provenance'
        || draft.provenance?.candidate_visible !== false) throw new Error('Use a requirements-only test draft with provenance.');
      core.validateContract(draft.contract);
      const choice = await vscode.window.showWarningMessage('Confirm that you reviewed each expected result against the trusted requirements. This freezes the test standard.',
        {modal: true}, 'Freeze reviewed suite');
      if (choice !== 'Freeze reviewed suite') return;
      const result = await service('/api/suites/freeze', draft, 'operator');
      if (!core.HASH.test(result?.suite_id || '')) throw new Error('The verifier did not return a valid suite ID.');
      await context.workspaceState.update('suiteId', result.suite_id);
      last = undefined;
      diagnostics.clear();
      summary = 'Suite frozen on this verifier service. Use that same suite for defective and corrected candidates.';
    },
    async selectSuite() {
      const suite = await vscode.window.showInputBox({title: 'Frozen suite ID from the verifier operator',
        value: context.workspaceState.get('suiteId', ''), validateInput: v => core.HASH.test(v) ? undefined : 'Enter the 64-character suite hash.'});
      if (!suite) return;
      if (!core.HASH.test(suite)) throw new Error('Invalid suite ID.');
      await context.workspaceState.update('suiteId', suite);
      summary = 'Suite selected. No new acceptance decision has been made.';
      last = undefined;
      diagnostics.clear();
    },
    async demoSuite() {
      if (setting('transport', 'direct') === 'agentverse') throw new Error('Load the demo suite directly on the remote verifier as its operator, then select that suite ID here.');
      const result = await service('/api/suites/demo', {}, 'operator');
      if (!core.HASH.test(result?.suite_id || '')) throw new Error('Invalid demo suite response.');
      await context.workspaceState.update('suiteId', result.suite_id);
      summary = 'Offline addition suite selected: 12 operator-authored cases. No live model test generation claimed.';
      last = undefined;
      diagnostics.clear();
    },
    async verify() {
      const snapshot = document('python');
      const suite = context.workspaceState.get('suiteId', '');
      if (!core.HASH.test(suite)) throw new Error('Select or freeze a test suite first.');
      const transport = setting('transport', 'direct');
      const verifierOrigin = origin();
      if (!['direct', 'agentverse'].includes(transport)) throw new Error('Configure a supported transport.');
      summary = 'Verification in progress. No current acceptance decision.';
      last = undefined;
      diagnostics.delete(snapshot.doc.uri);
      publish();
      try {
        const report = await progress('Chatmate: checking candidate against frozen tests',
          signal => service(transport === 'agentverse' ? '/api/verify-agent' : '/api/verify',
            {suite_id: suite, code: snapshot.source}, 'submit', signal));
        core.validateReport(report, snapshot.source, suite);
        if (origin() !== verifierOrigin || setting('transport', 'direct') !== transport
          || context.workspaceState.get('suiteId', '') !== suite) throw new Error('Verifier configuration changed during this request. Verify again.');
        if (transport === 'agentverse' && report.agent_signature_verified !== true) throw new Error('The gateway did not verify the agent signature.');
        const fresh = snapshot.doc.version === snapshot.version && core.hash(snapshot.doc.getText()) === snapshot.sourceHash;
        last = {kind: 'verification', freshness: fresh ? 'current' : 'stale', source_uri: snapshot.doc.uri.toString(),
          source_sha256: snapshot.sourceHash, verifier_origin: verifierOrigin, report};
        if (!fresh || report.decision === 'BLOCK') markBlocked(snapshot.doc, fresh ? report.reasons.join(' ') || 'Required checks failed.' : 'Source changed during verification. Verify the current source again.');
        summary = fresh ? `${report.decision}: ${report.passed}/${report.total} frozen tests passed. This is an editor precheck; CI enforces merge decisions.`
          : 'STALE / BLOCK: source changed during verification; rerun on the current file.';
        const directory = vscode.Uri.joinPath(context.globalStorageUri, 'reports');
        await vscode.workspace.fs.createDirectory(directory);
        await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(directory, report.run_id + '.json'), Buffer.from(JSON.stringify(last, null, 2)));
      } catch (error) {
        last = {kind: 'verification', freshness: 'incomplete', source_uri: snapshot.doc.uri.toString(),
          source_sha256: snapshot.sourceHash, report: {decision: 'BLOCK', reasons: [error.message]}};
        markBlocked(snapshot.doc, error.message);
        summary = 'BLOCK: required verification did not complete.';
        throw error;
      }
    },
    async crossReview(question) {
      const snapshot = document();
      if (typeof question !== 'string') question = await vscode.window.showInputBox({title: 'Ask Meta about the current file',
        prompt: 'Source and your question are sent to the verifier service and Meta.', value: 'Check correctness, security and edge cases.'});
      if (question === undefined) return;
      if (question.length > 4000) throw new Error('Questions must be at most 4000 characters.');
      const result = await progress('Chatmate: Meta advisory review', signal => service('/api/cross-review',
        {code: snapshot.source, language: snapshot.doc.languageId, question}, 'submit', signal));
      core.validateMeta(result, snapshot.source);
      const fresh = snapshot.doc.version === snapshot.version && core.hash(snapshot.doc.getText()) === snapshot.sourceHash;
      const entries = fresh ? result.review.findings.filter(f => f.line !== null).map(f => {
        const severity = {error: vscode.DiagnosticSeverity.Error, warning: vscode.DiagnosticSeverity.Warning, info: vscode.DiagnosticSeverity.Information}[f.severity];
        const diagnostic = new vscode.Diagnostic(new vscode.Range(f.line - 1, 0, f.line - 1, 0),
          `${f.message}\n${f.suggestion}`, severity);
        diagnostic.source = 'Chatmate Meta · advisory';
        return diagnostic;
      }) : [];
      advisory.set(snapshot.doc.uri, entries);
      // Advisory output cannot overwrite the independent gate result.
      await jsonDocument({kind: 'advisory', freshness: fresh ? 'current' : 'stale', source_uri: snapshot.doc.uri.toString(), ...result});
      summary = fresh ? 'Meta advisory review ready in the editor and Problems panel. It does not grant ACCEPT.' : 'Meta review is stale because the source changed.';
    },
    async showReport() {
      if (!last) throw new Error('Run verification first.');
      await jsonDocument(last);
    }
  };
  for (const command of COMMANDS) context.subscriptions.push(vscode.commands.registerCommand('chatmate.' + command, async (...args) => {
    if (!vscode.workspace.isTrusted) {await vscode.window.showErrorMessage('Trust the workspace before using Chatmate.'); return;}
    if (busy) {await vscode.window.showInformationMessage('A Chatmate operation is already running.'); return;}
    busy = true;
    publish();
    try {await handlers[command](...args);}
    catch (error) {summary = error.message; await vscode.window.showErrorMessage('Chatmate: ' + error.message);}
    finally {busy = false; publish();}
  }));
  const provider = {
    resolveWebviewView(webviewView) {
      view = webviewView;
      view.webview.options = {enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')]};
      const nonce = randomBytes(16).toString('hex');
      const js = view.webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri, 'media', 'panel.js'));
      const css = view.webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri, 'media', 'panel.css'));
      view.webview.html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${view.webview.cspSource}; script-src 'nonce-${nonce}'; connect-src 'none';"><link rel="stylesheet" href="${css}"></head><body>
        <span class="eyebrow">TRUST BUT VERIFY</span><h1>Chatmate<span>.</span></h1><p>Independent evidence before you merge.</p>
        <div id="summary" role="status">Ready</div><details><summary>Connection &amp; credentials</summary><button data-command="configureConnection">Connect verifier service</button><button data-command="configureSecret">Store or remove credential</button><p>ASI:One key stays in SecretStorage. Agentverse and Meta keys stay on the verifier host.</p></details>
        <h2>1 · Independent tests</h2><button data-command="newRequirements">Create requirements</button><button data-command="generateTests">Draft tests with ASI:One</button><button data-command="freezeSuite">Freeze reviewed draft · operator</button><button data-command="demoSuite">Use offline demo suite · operator</button>
        <h2>2 · Verify a candidate</h2><button data-command="selectSuite">Select frozen suite</button><p id="suite">No suite selected</p><button class="primary" data-command="verify">Verify active Python file</button><button data-command="showReport">Open last gate report</button>
        <h2>3 · Ask Meta</h2><form id="ask"><label for="question">Question about the active file</label><textarea id="question" maxlength="4000" rows="3" placeholder="Check edge cases and security…"></textarea><button type="submit">Ask for advisory review</button></form>
        <pre id="report"></pre><footer>Bounded integer functions only. Missing evidence blocks acceptance. A required CI gate enforces merges.</footer><script nonce="${nonce}" src="${js}"></script></body></html>`;
      context.subscriptions.push(view.webview.onDidReceiveMessage(message => {
        if (message?.type === 'ready') return publish();
        if (message?.type !== 'command' || !COMMANDS.includes(message.command)) return;
        if (message.command === 'crossReview') {
          if (typeof message.question !== 'string' || message.question.length > 4000) return;
          void vscode.commands.executeCommand('chatmate.crossReview', message.question);
        } else void vscode.commands.executeCommand('chatmate.' + message.command);
      }));
      publish();
    }
  };
  context.subscriptions.push(vscode.window.registerWebviewViewProvider('chatmate.panel', provider));
  context.subscriptions.push(vscode.workspace.onDidChangeTextDocument(event => {
    advisory.delete(event.document.uri);
    if (last?.source_uri === event.document.uri.toString() && core.hash(event.document.getText()) !== last.source_sha256) {
      last.freshness = 'stale';
      summary = 'STALE / BLOCK: source changed since the recorded verification. Rerun the gate.';
      markBlocked(event.document, 'Source changed since verification. The previous verdict no longer applies.');
    }
    publish();
  }));
  context.subscriptions.push(vscode.window.onDidChangeActiveTextEditor(publish));
  context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(event => {
    if (event.affectsConfiguration('chatmate')) {last = undefined; diagnostics.clear(); summary = 'Configuration changed. Verify again.'; publish();}
  }));
  publish();
  return {getState: () => ({summary, busy, last}), commandIds: COMMANDS.map(c => 'chatmate.' + c)};
}

module.exports = {activate, deactivate() {}};
