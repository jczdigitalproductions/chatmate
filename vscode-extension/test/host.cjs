const vscode = require('vscode');
const assert = require('node:assert/strict');
const fs = require('node:fs');
exports.run = async function() {
  try {
  const extension = vscode.extensions.getExtension('jczdigitalproductions.chatmate-verifier');
  assert.ok(extension, 'Extension must be discoverable in the real VS Code host');
  const api = await extension.activate();
  const registered = await vscode.commands.getCommands(true);
  for (const id of api.commandIds) assert.ok(registered.includes(id), id + ' registered');
  await vscode.commands.executeCommand('chatmate.open');
  await vscode.commands.executeCommand('chatmate.newRequirements');
  const doc = vscode.window.activeTextEditor.document;
  assert.equal(doc.languageId, 'json');
  const spec = JSON.parse(doc.getText());
  assert.deepEqual(Object.keys(spec).sort(), ['function', 'parameters', 'requirements']);
  assert.ok(api.getState().summary.includes('Candidate code is not read'));
  console.log('Real VS Code host: activation, 11 commands, sidebar, and requirements editor passed.');
  if (process.env.CHATMATE_HOST_RESULT) fs.writeFileSync(process.env.CHATMATE_HOST_RESULT,
    JSON.stringify({status: 'passed', message: 'Real VS Code host: activation, 11 commands, sidebar and requirements editor passed.'}));
  } catch (error) {
    if (process.env.CHATMATE_HOST_RESULT) fs.writeFileSync(process.env.CHATMATE_HOST_RESULT,
      JSON.stringify({status: 'failed', message: error.message}));
    throw error;
  }
};
