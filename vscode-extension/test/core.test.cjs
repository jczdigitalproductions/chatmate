const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../src/core');
const contract = JSON.parse(fs.readFileSync(path.join(__dirname, '../../demo/contract.json'), 'utf8'));
const spec = {requirements: contract.requirements, function: contract.function, parameters: contract.parameters};
const source = 'def add(a, b):\n    return a + b';
const report = () => ({decision: 'ACCEPT', run_id: 'b'.repeat(64), suite_id: 'a'.repeat(64), source_sha256: core.hash(source),
  passed: 12, total: 12, reasons: [], engine: 'chatmate-integer-v1',
  policy: {version: 'chatmate-gate-v2', required_pass_rate: 1, unsupported: 'BLOCK', missing_evidence: 'BLOCK', minimum_cases: 6, maximum_cases: 100, ai_review_is_gate: false}});
const response = value => new Response(JSON.stringify(value), {status: 200, headers: {'Content-Type': 'application/json'}});

test('blind ASI author sends only requirements; no implementation or key in provenance', async () => {
  let sent;
  const draft = await core.generateBlindDraft(spec, 'private-api-key', {fetchImpl: async (url, options) => {
    assert.equal(url, 'https://api.asi1.ai/v1/chat/completions');
    assert.equal(options.headers.Authorization, 'Bearer private-api-key');
    assert.equal(options.redirect, 'error');
    sent = JSON.parse(options.body);
    return response({choices: [{finish_reason: 'stop', message: {content: JSON.stringify({cases: contract.cases})}}]});
  }});
  assert.deepEqual(JSON.parse(sent.messages[1].content), spec);
  assert.equal(draft.provenance.candidate_visible, false);
  assert.ok(!JSON.stringify(draft).includes('private-api-key'));
  assert.ok(!JSON.stringify(sent).includes(source));
});
test('candidate source fields and executable test content are rejected', async () => {
  assert.throws(() => core.validateSpec({...spec, code: source}));
  assert.throws(() => core.validateContract({...contract, cases: [{args: [0, 0], expected: 'exec(code)'}]}));
  await assert.rejects(core.generateBlindDraft(spec, 'key', {fetchImpl: async () => response({choices: [{finish_reason: 'length', message: {content: '{}'}}]})}));
  await assert.rejects(core.generateBlindDraft(spec, 'key', {fetchImpl: async () => response({choices: [{finish_reason: 'stop', message: {content: '{"cases":[],"code":"exec"}'}}]})}));
});
test('duplicate cases and unsafe expected integers are rejected', () => {
  assert.throws(() => core.validateContract({...contract, cases: [...contract.cases, contract.cases[0]]}));
  const bad = structuredClone(contract);
  bad.cases[0].expected = Number.MAX_SAFE_INTEGER + 1;
  assert.throws(() => core.validateContract(bad));
});
test('service origin cannot contain credentials, paths or insecure remote HTTP', () => {
  for (const input of ['http://evil.example', 'https://u:p@example.com', 'https://example.com/api', 'https://example.com/?secret=x', 'file:///etc/passwd']) assert.throws(() => core.validateOrigin(input));
  assert.equal(core.validateOrigin('http://127.0.0.1:5050'), 'http://127.0.0.1:5050');
  assert.equal(core.validateOrigin('https://verifier.example'), 'https://verifier.example');
});
test('only matching nonempty, full-policy evidence can ACCEPT', () => {
  assert.equal(core.validateReport(report(), source, 'a'.repeat(64)).decision, 'ACCEPT');
  for (const override of [{source_sha256: '0'.repeat(64)}, {suite_id: 'c'.repeat(64)}, {run_id: '../secret'},
    {passed: 0, total: 0}, {passed: 11}, {engine: 'fake'}, {policy: {required_pass_rate: 0}}, {total: 101}]) {
    assert.throws(() => core.validateReport({...report(), ...override}, source, 'a'.repeat(64)));
  }
});
test('zero-test BLOCK is valid evidence; zero-test ACCEPT is not', () => {
  assert.equal(core.validateReport({...report(), decision: 'BLOCK', total: 0, passed: 0}, source, 'a'.repeat(64)).decision, 'BLOCK');
});
test('provider errors never print credentials or upstream response bodies', async () => {
  await assert.rejects(core.requestJson('https://example.com', {secret: 'keep-me-private', body: {},
    fetchImpl: async () => new Response('key=keep-me-private and secret code', {status: 401})}), error => !error.message.includes('keep-me-private') && error.message.includes('401'));
  await assert.rejects(core.requestJson('https://example.com', {secret: 'secret', body: {},
    fetchImpl: async () => {throw new Error('Authorization: Bearer secret');}}), error => !error.message.includes('Bearer'));
});
test('invalid and oversized response JSON is rejected', async () => {
  await assert.rejects(core.requestJson('https://example.com', {secret: 'key', body: {}, fetchImpl: async () => new Response('not json')}));
  await assert.rejects(core.requestJson('https://example.com', {secret: 'key', body: {}, fetchImpl: async () => new Response('x'.repeat(1000001))}), /size limit/);
});
test('cancellation prevents an acceptance decision', async () => {
  await assert.rejects(core.requestJson('https://example.com', {secret: 'key', body: {}, timeout: 5,
    fetchImpl: async (_url, {signal}) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))))}), /canceled or timed out/);
});
test('Meta evidence is explicitly advisory and source bound', () => {
  const review = {source_sha256: core.hash(source), advisory: true,
    review: {status: 'completed', summary: 'Inspect boundaries', findings: [], suggested_tests: []}};
  assert.equal(core.validateMeta(review, source).advisory, true);
  assert.throws(() => core.validateMeta({...review, advisory: false}, source));
  assert.throws(() => core.validateMeta({...review, source_sha256: 'c'.repeat(64)}, source));
});
