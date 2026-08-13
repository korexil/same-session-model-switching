# Provider adapter contract

An adapter translates one provider into the request and event vocabulary expected by the shell. It should be thin, explicit, and testable without the control panel.

## Required operations

```text
interface ProviderAdapter:
  describe() -> ProviderDescriptor
  authenticate(auth_profile) -> AuthResult
  list_models() -> [DiscoveredModel]
  probe(model, ProbeRequest) -> ProbeEvidence
  open_stream(model, NormalizedRequest) -> EventStream
  normalize_error(provider_error) -> TypedFailure
```

`list_models()` is discovery, not proof of usability. Only `probe()` can create availability evidence.

## Normalized request

```text
NormalizedRequest {
  messages
  system
  tools
  tool_choice
  max_output_tokens
  temperature?
  reasoning?
  images?
  metadata { session_id, request_id, switch_revision }
}
```

Adapters must reject unsupported fields or report a deliberate downgrade. Silently dropping a tool schema, image, system instruction, or reasoning control creates false continuity.

## Normalized stream events

```text
message_start { response_id, provider, model }
text_delta { text }
reasoning_delta { text }              // optional and policy-controlled
tool_call_start { call_id, name }
tool_call_delta { call_id, arguments }
tool_call_end { call_id }
usage { input_tokens, output_tokens, cache? }
message_end { stop_reason }
error { typed_failure }
```

The gateway should preserve ordering and stable tool-call IDs. Providers disagree on whether tool arguments arrive as JSON fragments, complete objects, or text; normalization must handle incremental parsing without inventing missing data.

The gateway should also expose the resolved route as structured, secret-free evidence: alias, provider, upstream model, transport, session ID, request ID, observation time, and expiry. A display name alone cannot detect fallback or alias drift.

## Typed failures

At minimum, distinguish:

| Type | Examples | Controller behavior |
| --- | --- | --- |
| `auth_missing` | no configured credential | reject; do not retry |
| `auth_rejected` | 401/403 | mark unavailable; operator action |
| `rate_limited` | 429, quota exhausted | short negative cache; try explicit fallback policy |
| `model_unknown` | bad alias or provider mapping | reject and quarantine registry entry |
| `capability_mismatch` | tools/images unsupported | reject for this session profile |
| `transport_failure` | timeout, connection reset | bounded retry or rollback |
| `provider_failure` | 5xx | short negative cache |
| `protocol_violation` | malformed stream or tool call | abort stream; preserve evidence |

Do not collapse all failures into “model unavailable.” Operators need to know whether to wait, fix credentials, update an alias, or disable a capability.

## Capability negotiation

Capabilities belong to `(provider, upstream_model)`, not to a marketing model name. The same underlying model can expose different windows, tool behavior, or media support through different providers.

Before a switch, compute:

```text
required_by_session - supported_by_target
```

If the result is non-empty, reject the switch or ask the operator to choose a declared downgrade. Never silently remove tools from a live agent session.

## Authentication boundary

An adapter declares one or more supported auth profiles, such as:

- native shell subscription,
- provider API key,
- provider-supported OAuth client,
- local gateway credential that maps to a supported upstream grant.

The existence of an OAuth token does not imply permission or technical compatibility to replay it through a different client. Authentication support is part of the adapter evidence, not an implementation detail.
