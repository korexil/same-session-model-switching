# Session continuity across models

## Continuity is evidence-backed replay

The new model does not inherit the old model's mind. It inherits the shell's explicit record:

- ordered user and assistant messages,
- tool calls and tool results,
- workspace state,
- session-scoped rules,
- externalized task state,
- and a small transition contract.

The model may reinterpret that evidence. This is a feature: changing models should not force agreement with unsupported conclusions.

## Four inheritance classes

| Class | Treatment after switching |
| --- | --- |
| User decisions and active commitments | inherit directly until explicitly changed |
| Reproducible facts | inherit when linked to a file, commit, command, or result whose dependencies remain valid |
| Unattributed claims | mark for verification if the next action depends on them |
| Volatile runtime facts | re-check just in time: process state, branch head, quota, time, availability |

Subjective judgments—priority, code quality, bug explanation, model preference—may be reconsidered, but the new model should state the evidence for disagreement.

## One-shot transition marker

After runtime verification, write a minimal marker:

```text
TransitionMarker {
  session_id
  from
  to
  created_at
}
```

On the next user turn, a hook may consume the marker and inject the inheritance policy once. The marker should not contain a snapshot of “facts”; snapshots decay and become a second source of truth.

Do not manufacture a user/assistant exchange solely to prove the switch; that pollutes the very transcript being preserved. Verification should come from route metadata on the next natural assistant response or from a shell/gateway control event explicitly excluded from conversation history. Until that evidence arrives, the UI stays `verifying` and persistent `desired` state remains unchanged.

Properties:

- exact-session scoped,
- time-bounded,
- consume-once,
- last writer wins before consumption,
- fail-open if the hook is broken,
- no new task or memory ledger.

## Session identity

Persist the exact session ID at launch. Resume only by explicit ID. Avoid “continue the latest session” behavior when probes, nested agents, or parallel shells can write transcripts in the same directory.

Status readers must resolve:

```text
session_id -> exact transcript -> latest assistant model evidence
```

They must not resolve:

```text
working_directory -> newest file by mtime -> guessed session
```

## Compaction and context windows

The shell decides when to compact based on the context window it believes the selected model has. A gateway alias that routes correctly but reports the wrong window can cause early compaction or oversized requests.

Treat context metadata as provider-scoped and verified. If the shell needs a special carrier alias to select a larger window, keep the human-facing alias, upstream ID, and context metadata as distinct fields. Never add a “large context” suffix to models that do not actually support it through that provider.

The preflight must use the current transcript estimate plus serialized tool schemas, system/control material, reserved output, and a safety margin. A static advertised window is a ceiling, not proof that the current session fits.

## Tool continuity

The transcript may contain tool schemas and prior tool results. Before switching, ensure the target can continue with the session's required tool profile. A plain-text probe is insufficient for `tool-verified` status; run a harmless tool-call probe and verify:

- name preservation,
- argument JSON integrity,
- call ID stability,
- streaming order,
- and result continuation.
