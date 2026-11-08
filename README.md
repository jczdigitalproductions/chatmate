# Chatmate v3 · VS Code independent verifier

The primary interface is now the [Chatmate VS Code extension](vscode-extension/README.md). Its ASI:One test author uses `ASI_ONE_API_KEY` in VS Code SecretStorage. The independent verifier/gateway keeps `AGENTVERSE_API_KEY` and `META_MODEL_API_KEY` in its own private environment. The Python gate, signed suites, replay and CI integration below remain the verification backend.

Build/install instructions, the exact credential split, and direct/Agentverse workflows are in the extension guide. `MODEL_API_KEY` is accepted as a legacy alias, but new service configurations should use `META_MODEL_API_KEY`. The legacy Python CLI can still draft tests with Meta; the VS Code generation command uses ASI:One instead.

## Retained verification backend

An independent verifier for AI-generated **small Python integer functions**. A requirements-only Meta test author proposes black-box cases. A trusted operator reviews and freezes them. Candidate agents can submit code against that suite, but cannot supply tests or change the acceptance policy. A bounded interpreter evaluates the code; every required test must pass. The gate returns `ACCEPT` or `BLOCK`, archives signed evidence, and exits nonzero on failure.

This is a focused hackathon MVP, not a general repository verifier. It prevents unsupported changes from receiving a passing decision. It supports pre-merge blocking; it does not implement deployment rollback.

## Run the offline proof

From this directory, with Python and `python-dotenv` installed:

```powershell
python -m pip install -r requirements.txt
python demo.py
```

The gate engine itself uses Python's standard library; uAgents is needed only for the Fetch adapter. Python 3.11/3.12 is recommended for uAgents compatibility. Tests and the offline demo were run locally on Python 3.14.

Expected demo output:

```text
defective: BLOCK (2/12 tests)
corrected: ACCEPT (12/12 tests)
injection: BLOCK (2/12 tests)
escape: BLOCK (0/0 tests)
... replay: ACCEPT
```

The escape is rejected before any case executes. Its zero-test result is a block, not a pass. The demo uses an explicitly operator-authored fixture, not live AI-generated tests. All four candidates use the same frozen suite. Full evidence and a summary are saved under `.chatmate-state/` (ignored by Git).

## Requirements-first test authoring

For the legacy CLI test author, create `.env` from `.env.example` without overwriting existing credentials, then set `META_MODEL_API_KEY`. The Meta model is configurable via `META_MODEL`. The VS Code test author instead uses ASI:One and its SecretStorage credential.

```powershell
python gate.py propose demo/requirements.json --output draft.json
# Inspect the cases and their expected results before approving them.
python gate.py freeze draft.json
```

The proposal command accepts **only** requirements, function name and parameter names. It does not accept a candidate path, source, diff or implementation transcript. Meta returns declarative `{args, expected}` cases, which the fixed harness turns into executable evaluations. Generated Python test code never executes on the host.

The operator must check the model's expected outputs. Requirements-first generation reduces implementation anchoring; a different agent/model alone does not eliminate shared blind spots or make an oracle correct. Ambiguous requirements must be resolved before freezing. The offline fixture can be frozen directly:

```powershell
python gate.py freeze demo/contract.json
```

Copy the printed suite ID for subsequent commands. Freezing fixes the requirements, cases, provenance and policy in a content-addressed HMAC-signed record. Later policy versions require freshly frozen suites.

## Verify and replay

```powershell
python gate.py verify --suite SUITE_ID --file demo/defective.py
python gate.py verify --suite SUITE_ID --file demo/corrected.py
python gate.py replay RUN_ID
```

Exit codes: `0` means ACCEPT, `1` means a verification BLOCK, `2` means configuration/input failure (also BLOCK). Model availability is not part of the deterministic gate: suites can run offline after freezing.

For an actual Git change, bind verification to immutable commits rather than a mutable working tree:

```powershell
python gate.py --state OPERATOR_STATE_DIRECTORY verify --suite SUITE_ID --repo REPOSITORY_DIRECTORY --base FULL_BASE_SHA --revision FULL_HEAD_SHA --file candidate.py
```

The repository change must modify **exactly that one approved source file**. Extra files, verifier edits, workflow edits, missing revisions and unsupported source block the change. This intentionally narrow rule avoids pretending that one verified function certifies unrelated changes. No hooks, candidate dependencies or candidate scripts run. Run the verifier itself from a trusted checkout, never the submitted revision.

Every completed gate evaluation archives the exact source, frozen contract, cases and outcomes, policy, commit context when provided, engine sources, Python/platform details, timestamp and HMAC signature. Public responses show the decision, totals, source/suite/run hashes and reasons, but omit private test vectors. Replay checks signatures and requires unchanged verifier sources, then reruns the archived source against the signed suite. Replay rejects altered evidence. Retain the verifier's Python version for environment reproduction.

The HMAC is an integrity check within the verifier trust boundary, not a publicly verifiable signature. Anyone with the key can forge records. Keep the state directory and key outside implementer-controlled worktrees in a real deployment. Archived source and model responses may be sensitive; do not publish the state directory.

## Web interface

Set two distinct random credentials of at least 32 characters in `.env`: `CHATMATE_OPERATOR_TOKEN` and `CHATMATE_SUBMIT_TOKEN`. Generate each with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

```powershell
python app.py
```

Open http://127.0.0.1:5050. The operator can generate/review/freeze a draft or use the offline demo suite. A submitter supplies a frozen suite ID and candidate code with a separate submission credential. Credentials are kept in page memory; the server refuses gate operations if the two configured credentials are missing, too short or identical.

API roles:

| Endpoint | Credential | Purpose |
|---|---|---|
| `POST /api/suites/draft` | Operator | Requirements-only Meta test draft |
| `POST /api/suites/freeze` | Operator | Sign an approved contract and provenance |
| `POST /api/suites/demo` | Operator | Freeze the known offline fixture |
| `POST /api/verify` | Submitter | `{suite_id, code}` only; no tests/policy accepted |
| `POST /api/review` | Submitter | Legacy static/Meta commentary; never an acceptance gate |

The web server is for loopback use. Run a deployed verifier under a separate operator account with authentication, HTTPS, rate limiting and private evidence storage. Repeated test probing can leak information even when vectors are withheld. The included demo tests are public; use a private suite for adversarial submissions.

## Fetch.ai integration

Set `FETCH_AGENT_SEED` and a comma-separated `FETCH_ALLOWED_SENDERS` allowlist. Pre-freeze suites using the operator CLI or web role, then run:

```powershell
python fetch_agent.py
```

Request and response schemas for a calling uAgent:

```python
from uagents import Model

class VerificationRequest(Model):
    suite_id: str
    code: str

class VerificationResponse(Model):
    decision: str
    report_json: str

# In your authorized generator's async handler:
# await ctx.send(CHATMATE_ADDRESS, VerificationRequest(suite_id=SUITE_ID, code=source))
```

Validate the response sender address. Only allowlisted signed senders receive service. No agent handler can create suites or change policy. The original `ReviewRequest`/`ReviewResponse` advisory protocol remains available. This is a structured uAgents protocol, not an ASI:One Chat Protocol deployment. Remote reachability, registration and credentials require your Fetch.ai setup.

## Connect a required merge gate

`integrations/chatmate-gate.yml.example` is a GitHub Actions integration template. It uses a protected-base checkout, fetches candidate Git objects as data, runs the trusted verifier, and posts the `chatmate/verifier` status on the exact PR head SHA. It never checks out or imports candidate code. `integrations/ci.py` handles the gate and status publication; missing configuration yields failure.

To activate it:

1. Commit the verifier and template to your protected base branch; install the template as `.github/workflows/chatmate-gate.yml`. Set its fixed `CHATMATE_TARGET_FILE` to the single approved function file.
2. Freeze an operator-reviewed suite. Add repository secrets `CHATMATE_SIGNING_KEY_B64` (base64 of the 32-byte `signing.key`) and `CHATMATE_SUITE_B64` (base64 of the corresponding signed suite JSON). Keep these separate from implementer access. These values are not Meta API credentials.
3. Configure branch protection to require **`chatmate/verifier`**, restrict the permitted status publisher where supported, require the branch to be current, and disallow bypasses. Protect verifier/workflow updates with owner review. Do not give implementers status-write credentials or a path to alter trusted workflows.
4. Store full CI evidence in an operator-controlled private archive if required. The example leaves private evidence in temporary runner storage and prints only the public summary; runner storage is not durable archival. Local/service runs retain full evidence in the configured state directory.

This integration is supplied but **has not been installed or run against a live GitHub repository**. Repository settings and secrets are not changed by the local demo. The GitHub workflow uses privileged `pull_request_target` solely to run trusted base code; replacing the protected checkout with a candidate checkout would violate its trust boundary. See [GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target) and [commit status API](https://docs.github.com/en/rest/commits/statuses).

## Supported semantics and limits

- Exactly one function with 1–6 named integer parameters; no defaults, annotations or decorators.
- Return integer/boolean results, local assignments, if/else and conditional expressions.
- Integer `+`, `-`, `*`, `//`, `%`, unary operations, comparisons, boolean operations and positional `abs/min/max`.
- No imports, attributes, filesystem/network access, dynamic calls, recursion, loops, classes, strings, containers or exceptions in submitted code. All syntax is checked, including dead branches.
- Source ≤50,000 characters/1,000 AST nodes; 2,000 evaluation steps per case; bounded integer inputs/intermediates; 6–100 distinct frozen cases. Failures, incomplete returns and arithmetic errors block acceptance.

The engine is a restricted interpreter, **not CPython execution or an OS/container sandbox**. It exposes only the supported arithmetic semantics and has no candidate-accessible host objects. Docker is not required. Its own implementation remains trusted code and has not received a security audit. Finite test success does not rule out overfitting or untested defects. A general-language verifier would need an externally isolated execution service and broader repository/dependency analysis.

## Validate

```powershell
python -m unittest -v test_reviewer.py test_gate.py
node --check static/app.js
```

Optional UI check: with Playwright and its Chromium browser installed, `node test_ui.cjs` starts a local test server, checks the frozen-suite → BLOCK → ACCEPT flow and mobile overflow, then closes its server/browser. Screenshots are saved in `.chatmate-state/`. Its credentials are test-only fixtures, not deployment secrets.

Tests cover defect/fix decisions, interpreter semantics, import/dynamic-call/dunder/loop/oversized arithmetic attacks, prompt-bearing comments, test/policy/evidence tampering, replay, hidden test vectors, independent author input, HTTP role separation, exact Git revision extraction, extra-file blocking, CLI exit codes and CI failure statuses. Meta calls and GitHub status publication are mocked; live Meta/Fetch.ai/GitHub behavior is not claimed.

API references: [Fetch.ai agent creation](https://uagents.fetch.ai/docs/getting-started/create), [Meta Model API quickstart](https://dev.meta.ai/docs/cookbook/quickstart-chat-completions).
