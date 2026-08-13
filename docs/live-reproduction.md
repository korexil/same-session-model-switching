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
- route evidence expiry forces a new probe;
- context/tool incompatibility is rejected before dispatch;
- a failed forward switch preserves the previous route;
- a failed rollback exposes `degraded/actual_unknown`;
- desired restart state is written only after runtime verification.

If any item is missing, describe the result with the lower evidence level from the README instead of calling it same-session switching.
