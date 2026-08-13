"""Credential-free transaction core for same-session model switching."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Callable, FrozenSet, Mapping, Optional, Protocol, Union
from uuid import uuid4


class State(str, Enum):
    READY = "ready"
    PROBING = "probing"
    QUEUED = "queued"
    VERIFYING = "verifying"
    ROLLING_BACK = "rolling_back"
    DEGRADED = "degraded"


class FailureKind(str, Enum):
    AUTH_MISSING = "auth_missing"
    AUTH_REJECTED = "auth_rejected"
    RATE_LIMITED = "rate_limited"
    MODEL_UNKNOWN = "model_unknown"
    CAPABILITY_MISMATCH = "capability_mismatch"
    TRANSPORT_FAILURE = "transport_failure"
    PROVIDER_FAILURE = "provider_failure"
    PROTOCOL_VIOLATION = "protocol_violation"


@dataclass(frozen=True)
class TypedFailure:
    kind: FailureKind
    safe_reason: str
    retry_after_seconds: Optional[float] = None


@dataclass(frozen=True)
class Unavailable:
    failure: TypedFailure
    expires_at: float


@dataclass(frozen=True)
class ModelEntry:
    alias: str
    provider: str
    upstream_model: str
    transport: str
    context_window: int
    capabilities: FrozenSet[str]
    safety_margin_tokens: int = 8_192


@dataclass(frozen=True)
class RouteEvidence:
    alias: str
    provider: str
    upstream_model: str
    transport: str
    session_id: str
    request_id: str
    switch_revision: int
    correlation_id: str
    observed_at: float
    expires_at: float

    def matches_route(self, entry: ModelEntry, session_id: str) -> bool:
        return (
            self.alias == entry.alias
            and self.provider == entry.provider
            and self.upstream_model == entry.upstream_model
            and self.transport == entry.transport
            and self.session_id == session_id
        )


@dataclass(frozen=True)
class Ticket:
    revision: int
    correlation_id: str
    session_id: str
    target: ModelEntry
    requested_at: float


@dataclass(frozen=True)
class Decision:
    action: str
    revision: int
    target: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class _Pending:
    ticket: Ticket
    probe_evidence: RouteEvidence


@dataclass
class _Active:
    ticket: Ticket
    dispatched_at: float
    rollback_expected: Optional[RouteEvidence]
    rollback_started_at: Optional[float] = None


class StateStore(Protocol):
    def load_desired(self) -> Optional[str]: ...

    def save_desired(self, alias: str, evidence: RouteEvidence) -> None: ...


class MemoryStateStore:
    """Non-durable default; inject a durable store in a live controller."""

    def __init__(self, desired: Optional[str] = None) -> None:
        self.desired = desired
        self.writes: list[tuple[str, str]] = []

    def load_desired(self) -> Optional[str]:
        return self.desired

    def save_desired(self, alias: str, evidence: RouteEvidence) -> None:
        self.desired = alias
        self.writes.append((alias, evidence.request_id))


ProbeResult = Union[RouteEvidence, TypedFailure]
Probe = Callable[[ModelEntry, str, int, str, float], ProbeResult]


class SwitchController:
    """Synchronous core suitable for wrapping in an async service."""

    def __init__(
        self,
        registry: Mapping[str, ModelEntry],
        *,
        desired: Optional[str] = None,
        actual: Optional[RouteEvidence] = None,
        state_store: Optional[StateStore] = None,
    ) -> None:
        self.registry = dict(registry)
        self.state_store = state_store or MemoryStateStore(desired)
        self.desired = desired if desired is not None else self.state_store.load_desired()
        if self.desired is not None and self.desired not in self.registry:
            raise ValueError("persisted desired alias is not in the registry")
        self.actual = actual
        self.pending: Optional[_Pending] = None
        self.unavailable: dict[str, Unavailable] = {}
        self.state = State.READY
        self._latest_revision = 0
        self._probing: Optional[Ticket] = None
        self._active: Optional[_Active] = None

    def begin(
        self,
        target_alias: str,
        *,
        session_id: str,
        transcript_tokens: int,
        reserved_output_tokens: int,
        now: float,
        control_tokens: int = 0,
        tool_schema_tokens: int = 0,
        required_capabilities: FrozenSet[str] = frozenset(),
    ) -> Ticket | Decision:
        if not session_id:
            return Decision("rejected", self._latest_revision, target_alias, "session_id_missing")
        token_counts = (transcript_tokens, control_tokens, tool_schema_tokens, reserved_output_tokens)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in token_counts):
            return Decision("rejected", self._latest_revision, target_alias, "invalid_token_estimate")
        if not math.isfinite(now):
            return Decision("rejected", self._latest_revision, target_alias, "invalid_time")
        self._expire_unavailable(now)
        entry = self.registry.get(target_alias)
        if entry is None:
            return Decision("rejected", self._latest_revision, target_alias, "unknown_alias")

        blocked = self.unavailable.get(target_alias)
        if blocked is not None:
            return Decision(
                "rejected",
                self._latest_revision,
                target_alias,
                f"unavailable:{blocked.failure.kind.value}:{blocked.failure.safe_reason}",
            )

        missing = required_capabilities - entry.capabilities
        if missing:
            return Decision(
                "rejected",
                self._latest_revision,
                target_alias,
                "missing_capabilities:" + ",".join(sorted(missing)),
            )

        available = entry.context_window - entry.safety_margin_tokens
        required_tokens = sum(token_counts)
        if required_tokens > available:
            return Decision(
                "rejected", self._latest_revision, target_alias, "context_would_not_fit"
            )

        already_actual = self.actual is not None and self.actual.matches_route(
            entry, session_id
        )
        if (
            already_actual
            and (self._probing is not None or self.pending is not None)
            and self._active is None
        ):
            self._latest_revision += 1
            self._probing = None
            self.pending = None
            self.state = State.READY
            return Decision("cancelled", self._latest_revision, target_alias, "switch_cancelled")
        if (
            already_actual
            and self._probing is None
            and self.pending is None
            and self._active is None
        ):
            return Decision("noop", self._latest_revision, target_alias, "already_actual")

        self._latest_revision += 1
        ticket = Ticket(
            self._latest_revision,
            uuid4().hex,
            session_id,
            entry,
            now,
        )
        self._probing = ticket
        self.pending = None
        self.state = self._active_state() or State.PROBING
        return ticket

    def finish_probe(
        self,
        ticket: Ticket,
        result: ProbeResult,
        *,
        busy: bool,
        now: float,
    ) -> Decision:
        stale = self._stale(ticket)
        if stale:
            return stale
        self._probing = None
        failure = self._probe_failure(ticket, result, now)
        if failure:
            self.state = self._active_state() or State.READY
            return failure

        assert isinstance(result, RouteEvidence)
        self.unavailable.pop(ticket.target.alias, None)
        if busy or self._active is not None:
            self.pending = _Pending(ticket, result)
            self.state = self._active_state() or State.QUEUED
            return Decision("queued", ticket.revision, ticket.target.alias)
        return self._ready_to_dispatch(ticket, now)

    def on_idle(self, *, now: float, probe: Probe) -> Decision:
        if self._active is not None:
            return Decision("noop", self._latest_revision, reason="switch_still_verifying")
        if self.pending is None:
            return Decision("noop", self._latest_revision, reason="nothing_pending")

        pending = self.pending
        stale = self._stale(pending.ticket)
        if stale:
            self.pending = None
            self.state = State.READY
            return stale

        result: ProbeResult = pending.probe_evidence
        if pending.probe_evidence.expires_at <= now:
            result = probe(
                pending.ticket.target,
                pending.ticket.session_id,
                pending.ticket.revision,
                pending.ticket.correlation_id,
                now,
            )
            failure = self._probe_failure(pending.ticket, result, now)
            if failure:
                self.pending = None
                self.state = State.READY
                return failure

        self.pending = None
        self.unavailable.pop(pending.ticket.target.alias, None)
        return self._ready_to_dispatch(pending.ticket, now)

    def verify_switch(
        self,
        ticket: Ticket,
        result: Optional[ProbeResult],
        *,
        now: float,
    ) -> Decision:
        active = self._active
        if active is None or active.ticket != ticket:
            return Decision("superseded", ticket.revision, ticket.target.alias)

        self._cache_failure(ticket.target.alias, result, now)
        failure = self._evidence_reason(
            ticket, result, now, not_before=active.dispatched_at, entry=ticket.target
        )
        if failure is None:
            assert isinstance(result, RouteEvidence)
            self.actual = result
            self._active = None
            self._drop_redundant_intent(result)
            try:
                self.state_store.save_desired(ticket.target.alias, result)
            except Exception:
                self._probing = None
                self.pending = None
                self.state = State.DEGRADED
                return Decision(
                    "degraded", ticket.revision, ticket.target.alias, "persistence_failed"
                )
            self.desired = ticket.target.alias
            self.state = self._settled_state()
            return Decision("committed", ticket.revision, ticket.target.alias)

        if active.rollback_expected is None:
            self.actual = None
            self._active = None
            self._probing = None
            self.pending = None
            self.state = State.DEGRADED
            return Decision("degraded", ticket.revision, reason="actual_unknown:" + failure)

        active.rollback_started_at = now
        self.state = State.ROLLING_BACK
        return Decision(
            "rollback_required",
            ticket.revision,
            active.rollback_expected.alias,
            "switch_verification_failed:" + failure,
        )

    def verify_rollback(
        self,
        ticket: Ticket,
        result: Optional[ProbeResult],
        *,
        now: float,
    ) -> Decision:
        active = self._active
        if (
            active is None
            or active.ticket != ticket
            or active.rollback_expected is None
            or active.rollback_started_at is None
        ):
            return Decision("rejected", ticket.revision, reason="rollback_not_expected")

        expected = active.rollback_expected
        expected_entry = self.registry.get(expected.alias)
        self._cache_failure(expected.alias, result, now)
        failure = (
            "rollback_route_missing"
            if expected_entry is None
            else self._evidence_reason(
                ticket,
                result,
                now,
                not_before=active.rollback_started_at,
                entry=expected_entry,
            )
        )
        if failure is None:
            assert isinstance(result, RouteEvidence)
            self.actual = result
            self._active = None
            self._drop_redundant_intent(result)
            self.state = self._settled_state()
            return Decision("rolled_back", ticket.revision, expected.alias)

        self.actual = None
        self._active = None
        self._probing = None
        self.pending = None
        self.state = State.DEGRADED
        return Decision(
            "degraded",
            ticket.revision,
            reason="rollback_unverified_actual_unknown:" + failure,
        )

    def _ready_to_dispatch(self, ticket: Ticket, now: float) -> Decision:
        if self._active is not None:
            raise RuntimeError("cannot dispatch while another switch is verifying")
        self._active = _Active(ticket, now, self.actual)
        self.state = State.VERIFYING
        return Decision("dispatch", ticket.revision, ticket.target.alias)

    def _probe_failure(
        self, ticket: Ticket, result: ProbeResult, now: float
    ) -> Optional[Decision]:
        if isinstance(result, TypedFailure):
            self._cache_failure(ticket.target.alias, result, now)
            return Decision(
                "rejected",
                ticket.revision,
                ticket.target.alias,
                f"{result.kind.value}:{result.safe_reason}",
            )
        reason = self._evidence_reason(
            ticket, result, now, not_before=ticket.requested_at, entry=ticket.target
        )
        if reason:
            return Decision("rejected", ticket.revision, ticket.target.alias, reason)
        return None

    def _settled_state(self) -> State:
        if self._probing is not None:
            return State.PROBING
        if self.pending is not None:
            return State.QUEUED
        return State.READY

    def _active_state(self) -> Optional[State]:
        if self._active is None:
            return None
        if self._active.rollback_started_at is not None:
            return State.ROLLING_BACK
        return State.VERIFYING

    def _drop_redundant_intent(self, evidence: RouteEvidence) -> None:
        current = self._probing
        if current is None and self.pending is not None:
            current = self.pending.ticket
        if current is None or not evidence.matches_route(current.target, current.session_id):
            return
        self._latest_revision += 1
        self._probing = None
        self.pending = None

    def _stale(self, ticket: Ticket) -> Optional[Decision]:
        if ticket.revision != self._latest_revision:
            return Decision("superseded", ticket.revision, ticket.target.alias)
        return None

    def _expire_unavailable(self, now: float) -> None:
        self.unavailable = {
            alias: item for alias, item in self.unavailable.items() if item.expires_at > now
        }

    def _cache_failure(
        self, alias: str, result: Optional[ProbeResult], now: float
    ) -> None:
        if not isinstance(result, TypedFailure):
            return
        retry = result.retry_after_seconds
        if retry is not None and math.isfinite(retry) and retry > 0:
            self.unavailable[alias] = Unavailable(result, now + retry)

    @staticmethod
    def _evidence_reason(
        ticket: Ticket,
        result: Optional[ProbeResult],
        now: float,
        *,
        not_before: float,
        entry: ModelEntry,
    ) -> Optional[str]:
        if result is None:
            return "evidence_missing"
        if isinstance(result, TypedFailure):
            return f"{result.kind.value}:{result.safe_reason}"
        if not all(map(math.isfinite, (now, not_before, result.observed_at, result.expires_at))):
            return "evidence_time_invalid"
        if result.expires_at <= result.observed_at:
            return "evidence_ttl_invalid"
        if result.observed_at > now:
            return "evidence_from_future"
        if result.expires_at <= now:
            return "evidence_expired"
        if result.switch_revision != ticket.revision:
            return "evidence_revision_mismatch"
        if result.correlation_id != ticket.correlation_id:
            return "evidence_correlation_mismatch"
        if result.observed_at < not_before:
            return "evidence_predates_action"
        if not result.matches_route(entry, ticket.session_id):
            return "evidence_route_mismatch"
        return None
