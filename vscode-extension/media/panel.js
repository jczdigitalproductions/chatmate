const vscode = acquireVsCodeApi();
for (const button of document.querySelectorAll('[data-command]')) {
  button.addEventListener('click', () => vscode.postMessage({type: 'command', command: button.dataset.command}));
}
document.getElementById('ask').addEventListener('submit', event => {
  event.preventDefault();
  vscode.postMessage({type: 'command', command: 'crossReview', question: document.getElementById('question').value || 'Check correctness, security and edge cases.'});
});
window.addEventListener('message', event => {
  const state = event.data;
  if (state?.type !== 'state') return;
  document.getElementById('summary').textContent = state.summary;
  document.getElementById('suite').textContent = state.suite ? `Suite: ${state.suite}` : 'No suite selected';
  document.getElementById('report').textContent = state.report ? JSON.stringify(state.report, null, 2) : '';
  for (const button of document.querySelectorAll('button')) button.disabled = !!state.busy;
});
vscode.postMessage({type: 'ready'});
