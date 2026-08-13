# Implementation guide

This guide turns the architecture into a concrete build order. It deliberately stops at provider-owned authentication boundaries: use an official API, an official client login, or a provider-supported connector. Do not extract or replay another application's OAuth tokens.

## Reproduce the control plane first

From the repository root, run:

```sh
python reference/demo.py
python -m unittest discover -s reference -p "test_*.py"
```

The first command must report one session, A → B → A, an intact six-message transcript, and a preserved workspace value. This is a deterministic positive control: if it fails, do not debug provider authentication yet.

The demo replaces only three production boundaries with in-memory equivalents: route probing, shell dispatch, and exact-session route observation. Everything else—the revision ordering, preflight, evidence matching, persistence order, and rollback semantics—is the same controller contract used by a live integration.

## 1. Choose the session owner

The session owner must retain the transcript, session ID, workspace, tool loop, and compaction state while a backend route changes. A Claude Code-style shell is a useful host because it can talk to an Anthropic-compatible gateway, but the controller is shell-neutral.

Record one immutable `session_id` when the shell starts. Never locate the session later by “newest transcript.”

## 2. Put a gateway behind the shell

The data plane is:

```text
shell -> Anthropic-compatible endpoint -> route adapter -> supported provider endpoint
```

For Claude Code, follow Anthropic's official LLM gateway configuration and set the gateway base URL and credential using its documented environment/settings mechanism. The gateway must preserve streaming order, tool-call IDs, model identity, request IDs, typed errors, and usage metadata.

An API-key provider is usually the shortest integration because the credential and endpoint are designed for programmatic use. A native product subscription may require a provider-supported connector or may remain usable only inside its official CLI.

## 3. Create one registry

Every selector, launcher, probe, and adapter reads the same registry. A safe entry includes:

```text
alias, provider, upstream_model, route_id, transport, auth_mode,
context_window, capabilities, support_level, evidence_ttl_seconds
```

Do not store credentials in it. Do not set `switchable` by hand; derive selectability from a non-expired evidence level and the current session requirements.

## 4. Implement three boundaries

The controller needs three environment-specific functions:

```text
probe(route, session_profile) -> RouteEvidence | TypedFailure
dispatch_switch(session_id, route, revision) -> acknowledgement
observe_route(session_id, after_revision) -> RouteEvidence | timeout
```

`RouteEvidence` should contain at least:

```text
alias, provider, upstream_model, transport,
session_id, request_id, observed_at, expires_at
```

The verification request should not become a fake user message. Prefer route metadata attached to the next natural assistant response, or a shell-emitted control event that is explicitly excluded from the conversation transcript.

## 5. Run the transaction

1. Validate alias, auth mode, required tools/media, and current transcript size.
2. Allocate a monotonic revision and probe the exact intended route.
3. If a newer revision exists when the probe finishes, discard this result.
4. If the shell is busy, keep only the newest pending request.
5. At the idle boundary, re-probe if evidence expired while queued.
6. Dispatch the switch and correlate its acknowledgement to the revision.
7. Observe the exact session after that revision.
8. If evidence matches, update `actual`, then persist `desired`.
9. If it mismatches or times out, request the previous route and verify rollback.
10. If rollback cannot be verified, clear `actual` and report `degraded/actual_unknown`.

The executable transaction model lives in [`../reference/switch_controller.py`](../reference/switch_controller.py).

## 6. Handle context honestly

A marketed context window is not sufficient evidence. The effective limit can depend on provider, route, account, tool schema size, shell metadata, and reserved output tokens.

Before dispatch, compare:

```text
estimated_transcript_tokens
+ serialized_tool_schema_tokens
+ system_and_control_tokens
+ reserved_output_tokens
<= verified_route_window - safety_margin
```

If it does not fit, reject visibly or ask the shell to compact before switching. Do not change the alias metadata merely to suppress a legitimate compact.

## 7. Wire the control surface

The UI sends only a registry alias and expected current revision. It never accepts arbitrary base URLs, model strings, commands, or credential paths.

Show all relevant states:

- `actual`: latest verified route;
- `desired`: restart intent;
- `pending`: queued last choice;
- `status`: probing, queued, verifying, rolling_back, ready, or degraded;
- precise typed failure and evidence age.

“Button clicked” and “command injected” are not success states.

## 8. Acceptance test

Do not publish a route as continuity-verified until all of these pass:

- A → B → A in one exact session without restarting the shell;
- transcript facts and workspace edits remain visible after each switch;
- a harmless tool call works before and after switching;
- two rapid choices commit only the last revision;
- a switch requested during generation waits for idle;
- queued evidence that exceeds its TTL is re-probed;
- wrong model evidence rolls back;
- failed rollback reports `actual_unknown`;
- a route that cannot fit the current transcript is rejected before dispatch;
- 401/403, 429, 5xx, timeout, malformed stream, and capability mismatch remain distinguishable.

Run the included control-plane tests with:

```sh
python -m unittest discover -s reference -p "test_*.py"
```

These tests validate transaction semantics only. Your adapter still needs integration tests against the provider's supported endpoint and the exact shell version you operate.
