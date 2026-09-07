# Live minimal integration

This opt-in harness turns the repository's abstract live boundary into one
small, reviewable program. One Python process owns a synthetic transcript and
temporary workspace while the backend path changes:

```text
Anthropic-compatible gateway (A) -> official Claude Code CLI (B) -> gateway (A)
```

Route B runs with `--safe-mode`, `--restricted`, `--strict-mcp-config`, only the
`Read` tool, and `--no-session-persistence`. It must recover one random marker
from the transcript and a second random marker from `marker.txt`. Route A must
then recover both markers after the switch back. Provider-private thinking
blocks never enter the provider-neutral transcript.

## Zero-credential rehearsal

```sh
python3 examples/live-minimal/live_minimal.py --check
```

This reads no environment variables and makes no requests. The regular mock
HTTP demo remains the full credential-free control-plane rehearsal.

## Live run

Copy `.env.example` values into your secret manager or shell environment; do
not commit a populated env file. The gateway token remains in an HTTP header and
is never included in the receipt.

```sh
export LIVE_GATEWAY_URL=http://127.0.0.1:8317
export LIVE_GATEWAY_TOKEN='...'
export LIVE_GATEWAY_VERSION='your exact gateway release and commit'
export LIVE_ROUTE_A='your-codex-route'
export LIVE_ROUTE_A_EXPECTED_MODEL='resolved-model-id'
export LIVE_CLAUDE_MODEL='your-supported-claude-model'
export LIVE_CLAUDE_EXPECTED_MODEL='resolved-claude-model-id'
export LIVE_EXPECT_CLAUDE_VERSION='2.1.259 (Claude Code)'

python3 examples/live-minimal/live_minimal.py --live
```

Plain HTTP is accepted only on loopback; remote gateways require HTTPS. A live
run makes two gateway completions and one Claude Code request, so it can consume
provider quota or incur charges. `LIVE_MAX_BUDGET_USD` defaults to `0.05` for
the Claude CLI request. Billing enforcement and subscription semantics remain
provider responsibilities.

The live command fails closed unless the gateway version is declared and the
observed Claude CLI version matches its exact expected value. The JSON receipt
contains those versions, the harness SHA-256, public model metadata,
usage counts, boolean assertions, and short SHA-256 digests of opaque IDs. It does not contain URLs,
tokens, prompts, responses, marker values, absolute paths, or raw provider
errors. Saving a receipt is opt-in:

```sh
python3 examples/live-minimal/live_minimal.py --live --receipt live-receipt.local.json
```

The ignore rules exclude `live-receipt*.json`. Review the receipt before
sharing it anyway: a model name or version can still be operational metadata in
some environments.

The harness digest canonicalizes UTF-8 source to LF before hashing, so the same
Git content verifies on Windows and Unix checkouts.

A secret-free receipt from the environment used to develop this example is
committed as [`verified-2026-09-07.json`](verified-2026-09-07.json).
It is evidence for those exact versions and routes, not a promise of current
provider availability.

## What this proves

- one outer session owner kept one transcript object across A -> B -> A;
- the resolved model returned by route A matched the configured expectation;
- route B received prior transcript state;
- the official Claude Code CLI used its built-in `Read` tool in an isolated
  temporary workspace;
- both synthetic markers survived the return to A.

It does not prove that two providers share hidden reasoning state or a
provider-owned server thread. It also does not replace the controller's
revision-correlated exact-session evidence required for a production switch.
