# Design decisions

## ADR-001: The shell owns continuity

**Decision:** Keep session identity, transcript, tools, and workspace in the agent shell. Treat models as replaceable backends.

**Why:** Provider-owned threads and hidden state are not portable. The shell already has the evidence needed to continue work.

**Trade-off:** The gateway must normalize more protocol differences, and provider-private optimizations may be lost after switching.

## ADR-002: Switch at an idle boundary

**Decision:** Probe immediately; apply only when the live shell is idle.

**Why:** Interactive shell commands compete with generation and prompt input.

**Trade-off:** Switching is not always instantaneous. A single last-writer-wins pending slot keeps the semantics understandable.

## ADR-003: Runtime evidence is authoritative

**Decision:** Determine the active model from the response or exact-session transcript.

**Why:** Configuration, UI state, and command acknowledgements describe intent, not execution.

**Trade-off:** Verification requires session correlation and version-aware transcript parsing.

## ADR-004: Probe with a real request

**Decision:** Availability requires a minimal completion through the real path.

**Why:** Discovery endpoints stay healthy through quota exhaustion and routing failures.

**Trade-off:** Probes cost a tiny amount, can consume rate limit, and must be bounded.

## ADR-005: Capabilities are provider-scoped

**Decision:** Store evidence by provider and upstream model, not only by model family.

**Why:** The same marketed model can have different context, tools, or media support through different routes.

**Trade-off:** The registry is more verbose but stops misleading alias reuse.

## ADR-006: Desired state commits last

**Decision:** Update restart intent only after runtime verification.

**Why:** A failed live switch should not poison the next restart.

**Trade-off:** The controller needs a transactional state store rather than a single configuration write.

## ADR-007: Transition markers contain policy, not facts

**Decision:** Write only session/from/to/time, then inject a stable inheritance policy once.

**Why:** Fact snapshots decay and duplicate the transcript or task ledger.

**Trade-off:** The new model may need a targeted re-check before acting.

## ADR-008: Authentication validity is part of adapter support

**Decision:** An adapter is not supported unless its credential path is supported for that client and provider.

**Why:** OAuth grants are scoped to clients and products; technical possession is not a generic delegation mechanism.

**Trade-off:** Some attractive model routes remain documented but intentionally non-switchable.

## ADR-009: Every switch is revisioned

**Decision:** Allocate a monotonic revision before probing and carry it through queueing, dispatch, confirmation, and observation.

**Why:** Asynchronous probes and UI clicks can finish out of order. Last-writer-wins must be enforced by the controller rather than guessed from arrival time.

**Trade-off:** Adapters and control events need one extra correlation field.

## ADR-010: Rollback requires evidence

**Decision:** A rollback is complete only when exact-session route evidence matches the previous route. Otherwise report `degraded/actual_unknown`.

**Why:** A successful command write or acknowledgement proves intent, not execution.

**Trade-off:** Recovery may remain visibly degraded until the next trustworthy response instead of offering optimistic status.

## ADR-011: Verification must not become conversation

**Decision:** Verify through route metadata on a natural assistant response or a non-conversation control event.

**Why:** Synthetic “say OK” turns consume quota, alter context, and can accidentally trigger agent behavior.

**Trade-off:** A quiet session can remain `verifying` until a trustworthy control event or natural response arrives.
