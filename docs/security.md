# Security and privacy

Same-session model switching expands the trust boundary: one conversation may cross multiple providers and authentication systems. The operator must be able to see and control that boundary.

## Threat model

Protect against:

- credentials leaking through config examples, command history, process arguments, logs, or UI errors;
- an untrusted control request selecting a more permissive or expensive provider;
- a gateway silently substituting a model;
- transcript or tool data being sent to a provider the operator did not select;
- stale status causing the operator to believe the session is on a different provider;
- unsafe OAuth reuse across clients;
- path traversal or injection through model aliases and control endpoints.

## Credential handling

- Keep secrets outside the repository and outside model-visible context.
- Pass credentials through the smallest possible process environment or OS secret store.
- Do not interpolate secrets into terminal commands, process titles, transcript text, or URLs.
- Redact normalized error messages before they cross into the UI.
- Bind each auth profile to an allowed provider and transport; do not let model aliases choose arbitrary credential sources.
- Back up configuration without printing or loosening permissions on the credential-bearing file.

## Control-plane authorization

Treat model switching as a privileged control action. A web panel or remote bot should authenticate the operator, validate a fixed registry alias, and call a narrow controller endpoint. It must not accept arbitrary base URLs, shell commands, credential paths, or upstream model strings.

## Provider disclosure

Before switching, the UI should disclose at least:

- provider and authentication mode,
- actual model alias and context window,
- required capability downgrades,
- fallback policy,
- and whether conversation/tool data will cross a new trust boundary.

## Audit events

Record structured, secret-free events:

```text
switch_requested(session_id, target, request_id)
probe_result(target, status, failure_type, latency)
switch_queued(session_id, target)
switch_dispatched(session_id, from, to)
switch_verified(session_id, actual, evidence_ref)
switch_rolled_back(session_id, reason)
fallback_applied(session_id, failed, actual, reason)
```

An evidence reference should be an opaque request or transcript locator, not a copied prompt or response.

## Public repository hygiene

Architecture-only publication should exclude:

- original source fragments and distinctive comments,
- hostnames, ports, usernames, filesystem layouts, service names, and panel routes,
- credentials and credential filenames,
- private model aliases and fallback ordering,
- transcript excerpts, prompts, memories, and personal names,
- production screenshots and logs,
- exact operational timings that reveal behavior patterns.

Use fictional aliases in examples and run both secret scanning and private-name scanning before publication.
