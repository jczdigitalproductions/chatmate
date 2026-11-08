# Chatmate · Trust but Verify

A VS Code extension for reviewing AI-generated code against independently authored, frozen tests. ASI:One drafts tests from requirements before receiving implementation code. A separate Python verifier evaluates supported candidates and returns ACCEPT/BLOCK evidence. Meta provides a second advisory review with findings in VS Code's Problems panel.

The editor is a precheck client. The protected CI gate remains the authority for merge blocking. Turning off the extension does not bypass a correctly configured required CI status.

## Install

In VS Code, open **Extensions → … → Install from VSIX…**, and select `chatmate-verifier-0.3.0.vsix` from this directory. For development, open this directory as a VS Code workspace and press **F5**; no compile step is needed. Open the Chatmate shield in the Activity Bar, or run **Chatmate: Open Verifier** from the Command Palette.

The verifier service is separate from the extension package. From the parent `chatmate` directory:

```powershell
python -m pip install -r requirements.txt
# Create a private .env using .env.example and set distinct operator/submit tokens.
python app.py
```

The existing server web page is retained as a fallback; VS Code is the primary interface for this version. The extension never starts Python from your workspace and never executes submitted code.

## Where each key goes

| Credential | Storage | Use |
|---|---|---|
| `ASI_ONE_API_KEY` | VS Code SecretStorage | Calls ASI:One's chat-completions API with only the requirements/function signature to draft tests. |
| `AGENTVERSE_API_KEY` | Gateway service's private `.env` | Authenticates Agentverse search for the pinned verifier agent. It is not the identity used to sign messages. |
| `META_MODEL_API_KEY` | Verifier/gateway service's private `.env` | Calls Meta's model API for an implementation-aware advisory review. |
| `CHATMATE_SUBMIT_TOKEN` | SecretStorage + verifier service configuration | Authorizes verification and advisory requests to your service. Separate from all provider keys. |
| `CHATMATE_OPERATOR_TOKEN` | Operator's SecretStorage + verifier service | Authorizes freezing tests and loading demo suites. Do not give it to a submitting agent. |
| `CHATMATE_AGENT_QUERY_TOKEN` | Gateway and remote verifier `.env` | Authenticates gateway queries on the separate uAgent. Never sent to the extension or Agentverse search. |

Use **Chatmate: Store or Remove Credential** for the three extension-side credentials. Prompts are masked. Values are not put in settings, workspace files, logs, webview HTML or reports. Agentverse and Meta keys intentionally have no extension-side entry field.

For the local demo, only the two Chatmate credentials are needed. Generate distinct tokens with `python -c "import secrets; print(secrets.token_urlsafe(32))"`, set them on the server, then enter them via the extension's credential command. ASI:One and Meta keys are unnecessary for the offline demo.

## Direct verifier workflow

1. Run **Configure Verifier Connection**. For a local service, use `http://127.0.0.1:5050` and **Direct verifier service**. Remote origins require HTTPS. Destinations are user-level settings; workspace overrides are ignored.
2. As the operator, choose **Create Behavior Requirements**. Edit the JSON contract containing exactly `requirements`, `function`, `parameters`.
3. With that JSON active, run **Generate Blind Tests with ASI:One**. Only the specification is sent. The draft opens in a JSON editor with declarative integer cases and provenance. It contains no API key.
4. Check every expected output against the requirements, then run **Freeze Reviewed Test Draft**. The server signs and stores the suite, returning its ID. Generated expectations are fallible; operator review is required.
5. Give the suite ID to the submitter. The submitter uses **Select Frozen Suite**, opens a Python candidate and chooses **Verify Active Python File**.
6. Inspect the sidebar, status bar and Problems panel. Unsupported source, missing evidence, test failures and outages block acceptance. Changing source invalidates the previous result; changes during an in-flight request make its result stale.
7. Use **Ask Meta to Review Active File** or the sidebar question field for a second review. Meta receives that file and question via the trusted service. Its findings are advisory and cannot overwrite the deterministic gate verdict.

The extension submits the whole active document, including unsaved text. It binds responses to that exact text's SHA-256 and frozen suite, not to a Git commit. The CI tool separately binds immutable revisions and rejects additional unverified file changes.

## Offline hackathon demo

With a direct service and the two Chatmate credentials configured:

1. Select **Load Offline Demo Suite** as the operator. This freezes 12 known, operator-authored addition tests; it does not claim live model generation.
2. Open `../demo/defective.py` and verify: BLOCK, 2/12 cases pass.
3. Open `../demo/corrected.py` and verify against the same suite: ACCEPT, 12/12 pass.
4. Verify `../demo/injection.py`: BLOCK. Verify `../demo/escape.py`: BLOCK before any test runs.
5. Change a verified file: the result becomes STALE / BLOCK until verified again.

## Agentverse transport

Deploy `../fetch_agent.py` on an operator-owned host with its frozen suites, `FETCH_AGENT_SEED`, and a private `CHATMATE_AGENT_QUERY_TOKEN` of at least 32 characters. Register that agent with a reachable HTTPS endpoint through the supported Fetch.ai deployment/registration process. The extension does not automatically create, fund or publish an agent.

Configure the gateway service with:

```dotenv
AGENTVERSE_API_KEY=your_private_agentverse_key
CHATMATE_AGENT_ADDRESS=the_exact_trusted_agent_address
CHATMATE_AGENT_QUERY_TOKEN=the_same_private_query_token_as_the_agent
```

Select **Agentverse through trusted gateway** in the connection command. The gateway uses the API key to search for the pinned active address, then `uagents.communication.send_sync_message` to query it. The request includes a random nonce and private query token. The gateway validates the returned envelope's signature, pinned sender, target, expiry, schema, nonce, source hash and suite ID. A different search result cannot replace the verifier. Missing discovery/agent dependencies or invalid replies block the request. There is no silent fallback to the direct verifier.

The signed envelope is archived on the gateway; full test execution evidence is retained on the remote verifier. Tests must be frozen on that remote verifier by its operator; freezing a suite on a separate gateway does not deploy it. Meta review still uses the gateway's server-side Meta key. The two provider services are not substitutes for an authenticated trusted verifier.

## Supported code and trust boundary

The retained deterministic engine supports a narrow integer-function subset: one function, 1–6 integer parameters, bounded arithmetic/comparisons, branches, assignments and selected pure builtins. It rejects imports, attributes, dynamic calls, loops, recursion, classes, strings and containers. This is a capability-free interpreter, not general CPython execution or an OS sandbox. Editor-side test drafts restrict expected integers to JavaScript's safe integer range.

Operator credentials, verifier code, signing keys, requirements and private tests are trusted. For independent operation, keep them on a separate operator account/service; storing an operator token beside a submitter in one developer session is only a convenience for the demo. Prompt separation reduces anchoring but does not eliminate shared model blind spots. Finite tests do not prove correctness or defeat all overfitting. Require rate limiting and protected CI for production use.

The extension uploads no source automatically and runs no workspace tasks. Only explicit generation, verification or review commands send their described inputs. Restricted/untrusted workspaces are unsupported. Model output is rendered as text; the sidebar has a restrictive content security policy and no network access. Private test vectors are omitted from submitter responses. Local public summaries are archived in VS Code's extension storage; full signed evidence remains on the verifier.

## Develop and test

```powershell
npm run check
npm test
npm run package
# Optional official test/packaging tools (requires network and Node.js 22+):
npm install --ignore-scripts
npm run test:host
npm run test:service
npm run package:vsce
```

`test:host` launches an isolated VS Code extension-development instance. Set `VSCODE_EXECUTABLE` to a local VS Code executable to use an existing installation; otherwise the official test runner downloads a test version. Provider tests use mock credentials/responses, not paid live requests. Native-host tests cover activation, command registration, the sidebar and the requirements editor.

`npm run package` uses the included Python standard-library offline builder and a fixed file allowlist. Runtime dependencies, network access and npm installation are unnecessary. ZIP timestamps are fixed for reproducibility. `package:vsce` is an alternative using Microsoft's packaging tool when its development dependencies are installed. The package is unsigned and intended for local VSIX installation; Marketplace publication is not performed.

The backend tests are run from the parent folder with `python -m unittest -v test_reviewer.py test_gate.py test_extension_service.py`. See the parent README for signed evidence, replay and required GitHub status setup.

API references: [ASI:One chat completions](https://docs.asi1.ai/documentation/build-with-asi-one/chat-completions), [Fetch.ai Agentverse search](https://innovationlab.fetch.ai/resources/docs/agentverse/searching), [uAgents communication source](https://github.com/fetchai/uAgents/blob/main/python/src/uagents/communication.py), [Meta model API](https://dev.meta.ai/docs/cookbook/quickstart-chat-completions), [VS Code SecretStorage](https://code.visualstudio.com/api/references/vscode-api#SecretStorage).
