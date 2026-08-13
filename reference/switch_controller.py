"""Credential-free reference state machine for same-session model switching.

Environment-specific code owns network probes, shell dispatch, and route observation.
This module owns ordering, preflight, evidence expiry, commit, and rollback semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, FrozenSet, Mapping, Optional


class State(str, Enum):
    READY = "ready"
    QUEUED = "queued"
    VERIFYING = "verifying"
    ROLLING_BACK = "rolling_back"
    DEGRADED = "degraded"


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
    observed_at: float
    expires_at: float

    def matches(self, entry: ModelEntry, session_id: str) -> bool:
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
    session_id: str
    target: ModelEntry


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


Probe = Callable[[ModelEntry, str, int, float], Optional[RouteEvidence]]


class SwitchController:
    """Small synchronous core suitable for wrapping in an async service.

    Allocate a ticket before starting an asynchronous probe. When the probe
    returns, ``finish_probe`` rejects it if a newer ticket exists. This is the
    last-writer-wins guard that prevents slow old requests from taking over.
    """

    def __init__(
        self,
        registry: Mapping[str, ModelEntry],
        *,
        desired: Optional[str] = None,
        actual: Optional[RouteEvidence] = None,
    ) -> None:
        self.registry = dict(registry)
        self.desired = desired
        self.actual = actual
        self.pending: Optional[_Pending] = None
        self.state = State.READY
        self._latest_revision = 0
        self._active: Optional[Ticket] = None
        self._rollback_expected: Optional[RouteEvidence] = None

    def begin(
        self,
        target_alias: str,
        *,
        session_id: str,
        transcript_tokens: int,
        reserved_output_tokens: int,
        required_capabilities: FrozenSet[str] = frozenset(),
    ) -> Ticket | Decision:
        revision = self._latest_revision + 1
        entry = self.registry.get(target_alias)
        if entry is None:
            return Decision("rejected", revision, target_alias, "unknown_alias")

        missing = required_capabilities - entry.capabilities
        if missing:
            return Decision(
                "rejected",
                revision,
                target_alias,
                "missing_capabilities:" + ",".join(sorted(missing)),
            )

        available = entry.context_window - entry.safety_margin_tokens
        if transcript_tokens + reserved_output_tokens > available:
            return Decision("rejected", revision, target_alias, "context_would_not_fit")

        # Only an accepted request enters the ordered transaction stream. A
        # typo or failed preflight must not supersede an already valid switch.
        self._latest_revision = revision
        return Ticket(revision, session_id, entry)

    def finish_probe(
        self,
        ticket: Ticket,
        evidence: Optional[RouteEvidence],
        *,
        busy: bool,
        now: float,
    ) -> Decision:
        stale = self._stale(ticket)
        if stale:
            return stale
        failure = self._invalid_evidence(ticket, evidence, now)
        if failure:
            self.state = State.READY
            return failure

        assert evidence is not None
        if busy:
            self.pending = _Pending(ticket, evidence)
            self.state = State.QUEUED
            return Decision("queued", ticket.revision, ticket.target.alias)

        return self._ready_to_dispatch(ticket)

    def on_idle(self, *, now: float, probe: Probe) -> Decision:
        if self.pending is None:
            return Decision("noop", self._latest_revision, reason="nothing_pending")

        pending = self.pending
        stale = self._stale(pending.ticket)
        if stale:
            self.pending = None
            self.state = State.READY
            return stale

        evidence = pending.probe_evidence
        if evidence.expires_at <= now:
            evidence = probe(
                pending.ticket.target,
                pending.ticket.session_id,
                pending.ticket.revision,
                now,
            )
            failure = self._invalid_evidence(pending.ticket, evidence, now)
            if failure:
                self.pending = None
                self.state = State.READY
                return failure

        self.pending = None
        return self._ready_to_dispatch(pending.ticket)

    def verify_switch(
        self,
        ticket: Ticket,
        evidence: Optional[RouteEvidence],
        *,
        now: float,
    ) -> Decision:
        if self._active != ticket or self._stale(ticket):
            return Decision("superseded", ticket.revision, ticket.target.alias)

        if evidence is not None and evidence.expires_at > now and evidence.matches(
            ticket.target, ticket.session_id
        ):
            self.actual = evidence
            self.desired = ticket.target.alias
            self._active = None
            self._rollback_expected = None
            self.state = State.READY
            return Decision("committed", ticket.revision, ticket.target.alias)

        if self._rollback_expected is None:
            self.actual = None
            self._active = None
            self.state = State.DEGRADED
            return Decision("degraded", ticket.revision, reason="actual_unknown")

        self.state = State.ROLLING_BACK
        return Decision(
            "rollback_required",
            ticket.revision,
            self._rollback_expected.alias,
            "switch_evidence_mismatch",
        )

    def verify_rollback(
        self,
        ticket: Ticket,
        evidence: Optional[RouteEvidence],
        *,
        now: float,
    ) -> Decision:
        expected = self._rollback_expected
        if self.state != State.ROLLING_BACK or self._active != ticket or expected is None:
            return Decision("rejected", ticket.revision, reason="rollback_not_expected")

        expected_entry = self.registry.get(expected.alias)
        if (
            evidence is not None
            and expected_entry is not None
            and evidence.expires_at > now
            and evidence.matches(expected_entry, ticket.session_id)
        ):
            self.actual = evidence
            self._active = None
            self._rollback_expected = None
            self.state = State.READY
            return Decision("rolled_back", ticket.revision, expected.alias)

        self.actual = None
        self._active = None
        self._rollback_expected = None
        self.state = State.DEGRADED
        return Decision("degraded", ticket.revision, reason="rollback_unverified_actual_unknown")

    def _ready_to_dispatch(self, ticket: Ticket) -> Decision:
        self._active = ticket
        self._rollback_expected = self.actual
        self.state = State.VERIFYING
        return Decision("dispatch", ticket.revision, ticket.target.alias)

    def _stale(self, ticket: Ticket) -> Optional[Decision]:
        if ticket.revision != self._latest_revision:
            return Decision("superseded", ticket.revision, ticket.target.alias)
        return None

    @staticmethod
    def _invalid_evidence(
        ticket: Ticket, evidence: Optional[RouteEvidence], now: float
    ) -> Optional[Decision]:
        if evidence is None:
            return Decision("rejected", ticket.revision, ticket.target.alias, "probe_failed")
        if evidence.expires_at <= now:
            return Decision("rejected", ticket.revision, ticket.target.alias, "probe_expired")
        if not evidence.matches(ticket.target, ticket.session_id):
            return Decision("rejected", ticket.revision, ticket.target.alias, "probe_route_mismatch")
        return None
