# Failure modes and lessons

These are the failure shapes that matter most in long-running, same-session switching. They are phrased generically and contain no deployment-specific code or paths.

## Discovery is not availability

**Misleading signal:** the gateway lists a model successfully.

**What can still be broken:** quota, OAuth scope, upstream route, model entitlement, request format, or provider health.

**Rule:** probe with a minimal real completion through the same protocol, auth profile, alias, and context carrier that the shell will use.

## Desired model is not actual model

**Misleading signal:** a config file or UI says the target model.

**What can still be broken:** the shell rejected the command, displayed a confirmation menu, auto-fell back, or the gateway substituted another route.

**Rule:** expose desired, actual, pending, and unavailable separately. Commit desired state only after exact-session runtime evidence matches.

## “Latest transcript” belongs to the wrong session

**Misleading signal:** the newest transcript file reports the probed model.

**What can still be broken:** an isolated probe, nested agent, or parallel session updated that file most recently.

**Rule:** persist a session ID at launch and read only its transcript.

## Switching while the shell is busy

**Symptoms:** command text appears in the prompt buffer, a hidden confirmation blocks the shell, generation is interrupted, or the request is lost.

**Rule:** probe immediately, but queue application until a verified idle boundary. Use one last-writer-wins pending slot rather than an unbounded queue.

## Confirmation UI is part of the protocol

Some shells present an interactive “switch model?” confirmation for aliases or provider changes. Treat this as a state, not as unexpected text. Correlate the confirmation to the requested target, choose only the expected action, and then verify the result.

Blind key injection is unsafe: terminal width, localization, and version changes can move the selection.

## Model aliases lie about context

A custom alias may route to the correct upstream while the shell assumes its default context size. Long conversations then compact early, or a large request fails unexpectedly.

**Rule:** keep upstream ID, selection alias, and provider-scoped context window separate. Verify the exact alias used by the shell.

## Automatic compaction retries an impossible route

**Symptoms:** after switching a long session, the shell repeatedly tries to compact but every attempt returns a size, auth, quota, or provider error.

**Cause:** compaction itself uses the selected backend, so the recovery request is sent through the same route that cannot accept it.

**Rule:** preflight before dispatch. Compact on the current verified route, or temporarily use a verified recovery route that can carry the raw request. If neither exists, stop retrying and start a new session from a bounded handoff. See [context-window recovery](context-window-recovery.md).

## Same model, different provider, different capability

Context length, tool use, images, prompt caching, and reasoning controls may differ between providers for the same marketed model.

**Rule:** registry keys should include provider identity. Never merge capability evidence solely by base model name.

## A global gateway switch degrades routes that never needed it

**Misleading signal:** after pointing the shell at the gateway, every model still answers correctly. Switching works. Nothing errors.

**What can still be broken:** a capability the *native* route carried — extended prompt-cache TTL, provider beta headers, reasoning controls — can be dropped in transit. The request succeeds and the content looks right; only the cost profile changes.

**Why it survives review:** the models that *required* the gateway usually cannot use that capability anyway, so its absence looks normal. The entire cost falls on the models that did not need the gateway at all — they were routed through it only because the switch was global. A capability regression can therefore run for weeks while every functional check stays green.

**Rule:** make route selection per-model, not a global mode. The operator switch should mean *“is the gateway available”*, not *“does everything go through the gateway”*. A model the native route can serve should take the native route even while the gateway is enabled; keep the global switch as an availability flag that the per-model decision reads.

**Rule:** liveness and readiness probes do not catch this — the request succeeds. Assert the capability itself: read back the provider's own accounting for the feature you depend on (usage or billing fields, response headers, echoed request options) and alert when it changes. A silent downgrade has no error surface; the only witness is the field itself.

## OAuth is not a portable API key

An OAuth login can succeed in an official product while requests through another shell fail—or violate the intended authorization boundary.

**Rule:** only advertise adapters whose auth path is explicitly supported. For example, a Gemini target is a valid architectural adapter, but an OAuth grant bound to an official Gemini client should not be presented as a generic CC gateway credential.

## Health checks test the wrong layer

**Misleading signal:** gateway process exists, TCP port is open, or `/models` returns 200.

**Rule:** distinguish liveness from readiness. Startup readiness and pre-switch probing should send a real request. The probe itself must report whether it failed because of auth, quota, transport, or protocol.

## Error detail disappears between layers

Gateway says “429 quota”; backend converts it to “500”; web server returns “HTTP Error”; UI says “switch failed.” The operator cannot tell whether to wait or repair configuration.

**Rule:** normalize typed failures once, preserve a safe human-readable reason through every layer, and never expose credentials or raw provider bodies.

## Multiple model lists drift

If the launcher, control panel, switch script, and gateway each maintain a list, one layer will accept an option another layer cannot route.

**Rule:** generate views from one registry. Add an invariant test comparing every selectable UI value with registry output.

## A slow probe wins after a newer choice

**Symptoms:** the operator selects B and then C, but B's slower health check finishes last and switches the shell back to B.

**Rule:** allocate a monotonic revision and unique correlation ID before each accepted probe. Probe, queue, dispatch, confirmation, and evidence must all match the latest transaction; older completions are `superseded`.

## Valid evidence proves the wrong switch

**Symptoms:** a previous A → B response remains inside its TTL, so a new A → B request appears verified before the new dispatch produces any evidence.

**Rule:** TTL and route equality are necessary but insufficient. Require matching revision and correlation ID, plus `observed_at >= requested_at` for probes and `observed_at >= dispatched_at` for commits. Reject a prior same-route observation even while it remains unexpired.

## Cancelling back to the current route does nothing

**Symptoms:** B is being probed, the operator selects the currently active A, the UI reports a no-op, and B switches in later.

**Rule:** selecting the active route while another probe or queued intent exists is cancellation, not a no-op. Advance the revision and clear the in-flight intent so its completion becomes stale.

## Queued evidence expires before dispatch

**Symptoms:** a model probed healthy while the shell was busy, then quota or authentication changed before the session became idle.

**Rule:** evidence has an expiry time. Re-probe at the idle boundary if its TTL elapsed; do not treat the old result as a permit.

## Rollback acknowledgement is mistaken for recovery

**Symptoms:** the target fails, a rollback command is sent, and the UI claims the old model even though no subsequent route evidence exists.

**Rule:** verify rollback like a forward switch. If it cannot be verified, clear `actual` and expose `degraded/actual_unknown`.

## A failed switch poisons restart state

Updating the persisted target before probing means a failed switch also breaks the next restart.

**Rule:** runtime verify first, persistence commit second. On failure, preserve old desired state unless the operator explicitly changes restart policy.

If runtime verification succeeds but the desired-state write fails, keep the verified `actual`, retain the old `desired`, and report `degraded/persistence_failed`. Do not roll back a healthy runtime route merely to hide a storage fault.

## Automatic fallback becomes invisible substitution

Fallback improves availability but can silently change cost, capability, privacy boundary, or behavior.

**Rule:** make fallback policy explicit and record the actual model. Never label a response as the requested model after substitution.

## Probe passes but tools fail

A one-token text completion does not prove tool calls, images, streaming, or long context.

**Rule:** support levels are cumulative. `probeable` is not `tool-verified` or `continuity-verified`.
