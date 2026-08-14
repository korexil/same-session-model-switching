# Context-window recovery without breaking the session

Same-session switching does not make context windows interchangeable. A transcript that fits route A may be too large for route B, and a shell may run compaction through the currently selected backend. If that backend is rate-limited or unavailable, automatic compaction can fail too.

The safe policy is **conditional compaction**, not “compact on every switch” and not “pretend every alias has the largest window.”

## Count the complete request

Use a provider- and route-specific verified window:

```text
required = transcript + tool schemas + system/control material + reserved output
usable(route) = verified context window - safety margin
```

Do not copy a large window value from another provider or from the marketed base model. The exact adapter, account, transport, tool mode, and shell alias must pass a long-context test before the registry may advertise that value.

## Decision table

| Condition | Safe action |
| --- | --- |
| Current request fits the target route | Switch directly; do not compact merely because the model changed |
| It does not fit, but a verified compacted request will fit and the current route is reachable | Compact on the current route, verify the new estimate, then switch |
| Current route cannot compact, but another reachable route can carry the full request | Switch to that recovery route, compact there, verify, then switch to the target |
| No reachable route can carry the full request, or the compacted request still exceeds the target | Start a new session with a bounded handoff artifact |

[`reference/context_planner.py`](../reference/context_planner.py) implements this table as a pure, credential-free function. It deliberately returns a new-session handoff instead of lying about capacity.

## Why automatic compaction can deadlock

A common failure sequence is:

1. a long session selects a smaller route;
2. the shell decides it must compact;
3. compaction is sent through the newly selected route;
4. that route rejects the oversized request, or returns 401/429/5xx;
5. every automatic retry repeats the same impossible request.

Prevent this by running context preflight **before dispatch**. If the switch already happened, restore the last verified route that can carry the uncompressed request, compact once, verify the reduced request size, and retry the target. A process liveness check or `/models` response is not enough; the recovery route needs a real completion probe.

## The handoff fallback

When no route can safely receive the current transcript, do not keep retrying and do not delete history blindly. Create a small, reviewable handoff containing only:

- the active objective and completion criteria;
- user decisions and constraints;
- reproducible facts with file/commit/result references;
- unresolved questions and the exact next action;
- no credentials, raw private logs, hidden reasoning, or unsupported conclusions.

Start a new session with that artifact and the same workspace. This is no longer literal same-session continuity, so the UI must say so. It is the honest recovery boundary.

## Operational rules

- Keep `declared_window`, `verified_window`, and the last long-context evidence separate.
- Expire long-context evidence when the provider, model, alias, transport, account class, or tool profile changes.
- Keep the last verified route until target verification succeeds; do not persist an unverified target.
- Do not append fake `1m`/`large` labels to aliases. Metadata can trigger shell behavior but cannot enlarge the upstream route.
- Do not compact on every switch: compaction is lossy and makes later models inherit a summary instead of the original transcript.
- After compaction, re-estimate the full request and run a harmless tool probe if the session depends on tools.

## Acceptance cases

At minimum, test:

1. large → small when the raw request already fits;
2. large → small after successful pre-switch compaction;
3. exhausted current route → reachable recovery route → compact → target;
4. compacted request still too large → explicit new-session handoff;
5. fake large-window metadata with a smaller real upstream limit → target remains unavailable;
6. automatic compaction returns 401/429/5xx → bounded retry, no loop;
7. tool schemas push an otherwise-fitting transcript over the target budget;
8. a model switch after compaction preserves exact-session evidence and does not accept an old observation.
