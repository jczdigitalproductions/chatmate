const $ = (id) => document.getElementById(id);
async function post(path, body, role) {
  const response = await fetch(path, {method: 'POST', headers: {
    'Content-Type': 'application/json', Authorization: `Bearer ${$(role + '-token').value}`
  }, body: JSON.stringify(body)});
  let result;
  try { result = await response.json(); } catch { throw new Error('The verifier did not return a valid response.'); }
  if (!response.ok) throw new Error(result.error || 'Verification request failed.');
  return result;
}
async function operatorAction(button, task) {
  button.disabled = true;
  $('operator-status').textContent = 'Preparing suite…';
  try { await task(); } catch (error) { $('operator-status').textContent = error.message; }
  finally { button.disabled = false; }
}
$('generate').onclick = () => operatorAction($('generate'), async () => {
  const result = await post('/api/suites/draft', {requirements: $('requirements').value,
    function: $('function').value, parameters: $('parameters').value.split(',').map(s => s.trim())}, 'operator');
  $('draft').value = JSON.stringify(result, null, 2);
  $('approved').checked = false;
  $('operator-status').textContent = 'Draft ready. Check expected outputs before freezing.';
});
$('freeze').onclick = () => operatorAction($('freeze'), async () => {
  if (!$('approved').checked) throw new Error('Review and confirm the expected outputs first.');
  const result = await post('/api/suites/freeze', JSON.parse($('draft').value), 'operator');
  $('suite').value = result.suite_id;
  $('operator-status').textContent = 'Suite frozen. Candidate submissions cannot change its tests.';
});
$('demo').onclick = () => operatorAction($('demo'), async () => {
  const result = await post('/api/suites/demo', {}, 'operator');
  $('suite').value = result.suite_id;
  $('operator-status').textContent = 'Offline demo suite frozen: 12 operator-authored addition cases. No live AI generation claimed.';
});
$('verify-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('submit').disabled = true;
  const entry = document.createElement('article');
  const heading = document.createElement('h2');
  const output = document.createElement('pre');
  heading.textContent = 'Verifying…';
  entry.append(heading, output);
  $('conversation').querySelector('.empty')?.remove();
  $('conversation').prepend(entry);
  try {
    const report = await post('/api/verify', {suite_id: $('suite').value, code: $('code').value}, 'submit');
    heading.textContent = `${report.decision} · ${report.passed}/${report.total} tests passed`;
    heading.className = report.decision === 'ACCEPT' ? 'accept' : 'block';
    output.textContent = [...report.reasons, `Engine: ${report.engine}`, `Suite: ${report.suite_id}`,
      `Source: ${report.source_sha256}`, `Evidence: ${report.run_id}`, '', report.scope].join('\n');
  } catch (error) { heading.textContent = 'BLOCK · verification incomplete'; output.textContent = error.message; }
  finally { $('submit').disabled = false; }
});
