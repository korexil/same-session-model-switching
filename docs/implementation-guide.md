# Implementation guide

This guide turns the architecture into a concrete build order. It deliberately stops at provider-owned authentication boundaries: use an official API, an official client login, or a provider-supported connector. Do not extract or replay another application's OAuth tokens.

## Reproduce the control plane first

From the repository root, run:

```sh
python reference/demo.py
python -m unittest discover -s reference -p "test_*.py"
```

The first command must report one session, A → B → A, an intact six-message transcript, and a preserved workspace value. This is a deterministic positive control: if it fails, do not debug provider authentication yet.

The demo replaces only three production boundaries with in-memory equivalents: route probing, shell dispatch, and exact-session route observation. Everything else—the transaction ordering, preflight, causal evidence matching, persistence order, cancellation, and rollback semantics—is the same controller contract used by a live integration.

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
probe(route, session_id, revision, correlation_id, now) -> RouteEvidence | TypedFailure
dispatch_switch(session_id, route, revision, correlation_id) -> acknowledgement | TypedFailure
observe_route(session_id, revision, correlation_id) -> RouteEvidence | TypedFailure
```

`RouteEvidence` should contain at least:

```text
alias, provider, upstream_model, transport,
session_id, request_id, switch_revision, correlation_id,
observed_at, expires_at
```

The revision establishes order inside one controller instance; the globally unique correlation ID prevents evidence from another process lifetime or coincidentally reused revision from being accepted. Probe evidence must be observed after `requested_at`; switch evidence must be observed after `dispatched_at`; rollback evidence must be observed after rollback dispatch.

The included [`HttpBridge`](../reference/http_bridge.py) is a standard-library client for these three boundaries. Point it only at localhost or HTTPS and implement the matching server endpoints described in [the live reproduction guide](live-reproduction.md). Forward and rollback calls carry an explicit phase and route while retaining the transaction identifiers. The bridge server remains shell/gateway-specific and owns the supported credential integration; the controller never receives provider secrets.

The verification request should not become a fake user message. Prefer route metadata attached to the next natural assistant response, or a shell-emitted control event that is explicitly excluded from the conversation transcript.

## 5. Run the transaction

1. Validate alias, auth mode, required tools/media, and the complete current context estimate.
2. Allocate a monotonic revision plus unique correlation ID and probe the exact intended route.
3. If a newer revision exists when the probe finishes, discard this result.
4. If the shell is busy, keep only the newest pending request.
5. At the idle boundary, re-probe if evidence expired while queued.
6. Dispatch the switch and correlate its acknowledgement to both transaction fields.
7. Observe the exact session after dispatch, requiring the same revision and correlation ID.
8. If evidence matches, update `actual`, then persist `desired`.
9. If it mismatches or times out, request the previous route and verify rollback.
10. If rollback cannot be verified, clear `actual` and report `degraded/actual_unknown`.

Selecting the already-active route while a different probe or queued request exists is an explicit cancellation. It advances the revision so a late result cannot resurrect the cancelled switch.

Persist restart intent through the `StateStore` contract only after step 8. [`JsonStateStore`](../reference/state_store.py) is an atomic file implementation. A persistence failure leaves the verified runtime route in `actual`, preserves the old `desired`, and reports `degraded/persistence_failed` instead of lying about either one.

The executable transaction model lives in [`../reference/switch_controller.py`](../reference/switch_controller.py).

## 6. Handle context honestly

A marketed context window is not sufficient evidence. The effective limit can depend on provider, route, account, tool schema size, shell metadata, and reserved output tokens.

Before dispatch, compare:

```text
transcript_tokens
+ tool_schema_tokens
+ control_tokens
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
- two rapid choices made before dispatch commit only the last revision;
- a newer choice made after dispatch waits while the active switch or rollback is verified, then runs as the sole pending transaction;
- choosing the active route cancels an in-flight probe or queued switch;
- unexpired evidence from an earlier same-route request is rejected;
- wrong revision or correlation ID is rejected;
- a switch requested during generation waits for idle;
- queued evidence that exceeds its TTL is re-probed;
- wrong model evidence rolls back;
- failed rollback reports `actual_unknown`;
- a route that cannot fit the current transcript is rejected before dispatch;
- invalid or non-finite token/time evidence is rejected rather than coerced;
- 401/403, 429, 5xx, timeout, malformed stream, and capability mismatch remain distinguishable.
- failed desired-state persistence is visible and never occurs before runtime verification.

Run the included control-plane tests with:

```sh
python -m unittest discover -s reference -p "test_*.py"
```

These tests validate transaction semantics only. Your adapter still needs integration tests against the provider's supported endpoint and the exact shell version you operate.
