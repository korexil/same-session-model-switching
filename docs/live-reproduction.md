# From the demo to a live shell

The included demo proves the controller and continuity invariants without credentials. A live reproduction adds four replaceable pieces; none should be rewritten inside the controller.

## Required pieces

| Piece | Reusable option | Evidence required before claiming success |
| --- | --- | --- |
| Session owner | Claude Code or another long-running tool shell | One unchanged session ID before and after A → B → A |
| Protocol gateway | An Anthropic-compatible gateway | A real completion, not only `/models` or process liveness |
| Provider routes | Supported API key, plan key, or provider-supported connector | Provider + upstream model + request ID from the actual response path |
| Control/evidence bridge | Your shell/gateway-specific adapter | Revision-correlated dispatch and exact-session route observation |

## Fastest route: supported programmatic credentials

For the first live build, use two providers whose credentials are explicitly intended for programmatic clients. This removes OAuth portability from the debugging surface.

1. Install the agent shell and one gateway that exposes an Anthropic-compatible endpoint.
2. Configure two provider routes with API keys or plan-specific provider keys.
3. Configure the shell through its documented gateway settings. For Claude Code, follow Anthropic's LLM gateway documentation rather than copying environment variables from an old blog post.
4. Keep one shell session open. Bind the controller to that exact session ID.
5. Implement `probe`, `dispatch_switch`, and `observe_route` from the [implementation guide](implementation-guide.md).
6. Run the full A → B → A acceptance list and retain secret-free route evidence.

## Generic bridge contract

[`reference/http_bridge.py`](../reference/http_bridge.py) provides the client side of a small vendor-neutral bridge. It accepts plain HTTP only for loopback hosts; remote endpoints must use HTTPS. An optional bearer token protects your bridge itself and is never part of route evidence.

Implement these JSON endpoints next to the shell or gateway:

| Endpoint | Purpose | Successful response |
| --- | --- | --- |
| `POST /v1/probe` | Send a minimal real request through the intended route | `{ "evidence": RouteEvidence }` |
| `POST /v1/switch` | Apply the target to the exact idle session | `{ "accepted": true }` |
| `POST /v1/evidence` | Read post-dispatch evidence for the exact session | `{ "evidence": RouteEvidence }` |

All requests contain:

```json
{
  "session_id": "opaque-session-id",
  "switch_revision": 7,
  "correlation_id": "globally-unique-transaction-id",
  "requested_at": 1234.5,
  "phase": "forward",
  "route": {
    "alias": "route-b",
    "provider": "provider-b",
    "upstream_model": "model-b",
    "transport": "gateway-b",
    "context_window": 100000,
    "capabilities": ["streaming", "tools"],
    "safety_margin_tokens": 8192
  }
}
```

`phase` is one of `probe`, `forward`, or `rollback`. A rollback keeps the original revision and correlation ID but sends the previous route in `route`; use `bridge.dispatch(ticket, route=previous, phase="rollback")` and observe it with the same route and phase. This prevents an adapter from accidentally dispatching the failed forward target again.

Every evidence object must echo the exact `switch_revision` and `correlation_id`, identify the full resolved route and session, and carry `request_id`, `observed_at`, and `expires_at`. A failure response is:

```json
{
  "failure": {
    "kind": "rate_limited",
    "safe_reason": "quota_exhausted",
    "retry_after_seconds": 30
  }
}
```

Do not return provider credentials, cookies, authorization headers, raw upstream error bodies, transcripts, or prompts. The bridge server is intentionally not universal: shell command/IPC semantics and supported provider authentication remain local adapter responsibilities.

Two relevant open-source building blocks are:

- [Claude Code Router](https://github.com/musistudio/claude-code-router) (MIT): a local gateway/control plane that describes Claude Code support, stable local endpoints, provider/model routing, logs, and multiple protocols.
- [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) (MIT): a multi-protocol proxy that describes adapters for several official coding CLIs and compatible clients.

They are **optional building blocks, not transitive proof**. Their model lists and login flows can change. Verify the exact release, license, provider terms, route identity, tool behavior, and context window you deploy. This project does not vendor, endorse, or automatically trust either runtime.

## Subscription routes

There is no universal “use my subscription” switch:

- If a paid plan issues a documented provider key, integrate it like an API route and label it `plan_api_key`.
- If an official CLI supports account sign-in, that proves the subscription works in that CLI—not automatically through another shell.
- A bridge may be used only when its credential flow and the upstream provider permit that client relationship.

Start with API/provider-key routes, make continuity pass, then add subscription connectors one at a time. Otherwise a failed switch cannot be cleanly attributed to the controller, gateway, OAuth scope, entitlement, quota, or provider policy.

## Definition of “similar behavior”

A live system reaches the level described by this repository only when all are true:

- the shell process and session ID do not change;
- visible transcript, tools, and workspace survive A → B → A;
- the next natural response comes from the verified target route;
- a busy generation queues exactly one last-writer-wins selection;
- old probe results cannot override a newer choice;
- prior same-route evidence cannot verify a new transaction;
- selecting the active route cancels an in-flight or queued different route;
- route evidence expiry forces a new probe;
- context/tool incompatibility is rejected before dispatch;
- a failed forward switch preserves the previous route;
- a failed rollback exposes `degraded/actual_unknown`;
- desired restart state is written only after runtime verification;
- persistence failure reports verified `actual` separately from unchanged `desired`.

If any item is missing, describe the result with the lower evidence level from the README instead of calling it same-session switching.
