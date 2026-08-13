# Adding a provider or custom model

Use this as an evidence ladder. Do not add the model to the main selector before the required level passes.

## 1. Define the boundary

- Name the provider, transport, upstream model, and human-facing alias separately.
- Choose an authentication profile explicitly supported by the provider and client.
- Record the provider-scoped context window and source date.
- Declare required shell capabilities: streaming, tools, images, reasoning controls, caching.

## 2. Implement normalization

- Convert shell requests into provider requests without silently dropping fields.
- Normalize text and tool-call streams into stable events.
- Preserve request IDs, response IDs, model identity, usage, and stop reasons.
- Convert provider errors into the typed failure taxonomy.

## 3. Pass evidence levels

### `documented`

- Protocol and auth path are documented.
- Known limitations are explicit.

### `probeable`

- A minimal real completion succeeds through the production-equivalent path.
- 401/403, 429, timeout, unknown model, and malformed response are distinguishable.

### `switchable`

- The live shell selects the alias without restart.
- Any confirmation flow is handled safely.
- Exact-session evidence reports the expected provider and model.
- Failure preserves the old model and session.

### `continuity-verified`

- A conversation switches A → target → A without losing visible transcript or workspace state.
- Busy-session switching queues and later applies.
- Multiple rapid choices before dispatch use last-writer-wins behavior; a choice after dispatch waits for the active transaction to settle.
- Desired state updates only after verification.

### `tool-verified`

- A harmless tool call streams correctly.
- Tool name, arguments, call ID, and result continuation survive normalization.
- Unsupported tool features are rejected or visibly downgraded.

### `long-context-verified`

- The exact shell alias reports the correct provider-scoped window.
- Compaction does not occur at the shell's default threshold by mistake.
- Oversized requests fail predictably and do not corrupt session state.

## 4. Add to the registry

Add one entry and generate all selectors and launcher validation from it. Do not hand-edit a panel list.

Minimum fields:

```text
alias, provider, upstream_model, route_id, transport, auth_mode,
context_window, safety_margin, capability flags,
evidence_level, evidence_ref, verified_at, evidence_ttl
```

Do not store a hand-maintained `switchable: true` as truth. Derive whether the UI may select an entry from its unexpired evidence and the current session's capability/context requirements.

## 5. Run negative tests

- unknown alias,
- wrong running mode,
- missing credential,
- rejected credential,
- exhausted quota,
- provider 5xx,
- gateway timeout,
- model listed but completion rejected,
- shell busy,
- confirmation text changed,
- transcript belongs to another session,
- switch acknowledgement without matching runtime evidence,
- tool capability mismatch,
- incorrect context metadata.
- slow older probe completing after a newer selection,
- queued probe evidence expiring before the idle boundary,
- rollback command succeeding without matching route evidence,
- current transcript and tools exceeding the route's verified window.

## 6. Expose it to operators

Show provider, auth mode, context window, capability gaps, evidence age, and fallback behavior. A disabled entry with a precise reason is more trustworthy than an option that fails silently.

## Gemini-specific caution

Gemini is a useful target for the adapter contract, but verify the credential path independently. A Google OAuth session created for an official Gemini client is not automatically reusable by a Claude Code-style shell or third-party gateway. If only the official shell is authorized, mark the adapter `documented` rather than `switchable`.
