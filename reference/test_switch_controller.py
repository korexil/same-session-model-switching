from __future__ import annotations

import unittest

from switch_controller import (
    FailureKind,
    MemoryStateStore,
    ModelEntry,
    RouteEvidence,
    State,
    SwitchController,
    Ticket,
    TypedFailure,
)


def entry(alias: str, context: int = 100_000) -> ModelEntry:
    return ModelEntry(
        alias=alias,
        provider=f"provider-{alias}",
        upstream_model=f"upstream-{alias}",
        transport="gateway",
        context_window=context,
        capabilities=frozenset({"streaming", "tools"}),
        safety_margin_tokens=1_000,
    )


def evidence(
    model: ModelEntry,
    session: str,
    now: float,
    *,
    ticket: Ticket | None = None,
    ttl: float = 30,
) -> RouteEvidence:
    return RouteEvidence(
        alias=model.alias,
        provider=model.provider,
        upstream_model=model.upstream_model,
        transport=model.transport,
        session_id=session,
        request_id=f"request-{model.alias}-{now}",
        switch_revision=ticket.revision if ticket else 0,
        correlation_id=ticket.correlation_id if ticket else "initial-route",
        observed_at=now,
        expires_at=now + ttl,
    )


class FailingStore(MemoryStateStore):
    def save_desired(self, alias: str, route_evidence: RouteEvidence) -> None:
        raise OSError("simulated persistence failure")


class SwitchControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = entry("a")
        self.b = entry("b")
        self.c = entry("c")
        self.session = "session-under-test"
        self.a_actual = evidence(self.a, self.session, 0, ttl=1_000)
        self.store = MemoryStateStore("a")
        self.controller = SwitchController(
            {"a": self.a, "b": self.b, "c": self.c},
            actual=self.a_actual,
            state_store=self.store,
        )

    def begin(self, alias: str, now: float = 10):
        return self.controller.begin(
            alias,
            session_id=self.session,
            transcript_tokens=10_000,
            reserved_output_tokens=2_000,
            required_capabilities=frozenset({"tools"}),
            now=now,
        )

    def test_happy_path_persists_only_after_causal_verification(self):
        ticket = self.begin("b")
        decision = self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        self.assertEqual("dispatch", decision.action)
        self.assertEqual([], self.store.writes)

        result = self.controller.verify_switch(
            ticket, evidence(self.b, self.session, 11, ticket=ticket), now=11
        )
        self.assertEqual("committed", result.action)
        self.assertEqual([("b", "request-b-11")], self.store.writes)
        self.assertEqual("b", self.controller.desired)
        self.assertEqual("b", self.controller.actual.alias)

    def test_busy_queue_reprobes_expired_evidence(self):
        ticket = self.begin("b")
        queued = self.controller.finish_probe(
            ticket,
            evidence(self.b, self.session, 10, ticket=ticket, ttl=2),
            busy=True,
            now=10,
        )
        self.assertEqual("queued", queued.action)
        calls = []

        def reprobe(model, session, revision, correlation_id, now):
            calls.append((model.alias, session, revision, correlation_id))
            return evidence(model, session, now, ticket=ticket)

        decision = self.controller.on_idle(now=20, probe=reprobe)
        self.assertEqual("dispatch", decision.action)
        self.assertEqual(ticket.correlation_id, calls[0][3])

    def test_slow_old_probe_cannot_override_latest_choice(self):
        old_ticket = self.begin("b", now=10)
        new_ticket = self.begin("c", now=11)
        old_result = self.controller.finish_probe(
            old_ticket,
            evidence(self.b, self.session, 12, ticket=old_ticket),
            busy=False,
            now=12,
        )
        new_result = self.controller.finish_probe(
            new_ticket,
            evidence(self.c, self.session, 12, ticket=new_ticket),
            busy=False,
            now=12,
        )
        self.assertEqual("superseded", old_result.action)
        self.assertEqual("dispatch", new_result.action)

    def test_new_choice_waits_while_dispatched_switch_is_verified(self):
        first = self.begin("b", now=10)
        first_probe = self.controller.finish_probe(
            first,
            evidence(self.b, self.session, 10, ticket=first),
            busy=False,
            now=10,
        )
        self.assertEqual("dispatch", first_probe.action)

        latest = self.begin("c", now=11)
        queued = self.controller.finish_probe(
            latest,
            evidence(self.c, self.session, 11, ticket=latest),
            busy=False,
            now=11,
        )
        self.assertEqual("queued", queued.action)
        self.assertEqual(State.VERIFYING, self.controller.state)
        blocked = self.controller.on_idle(now=11, probe=lambda *args: None)
        self.assertEqual("switch_still_verifying", blocked.reason)

        first_commit = self.controller.verify_switch(
            first, evidence(self.b, self.session, 12, ticket=first), now=12
        )
        self.assertEqual("committed", first_commit.action)
        self.assertEqual(State.QUEUED, self.controller.state)
        self.assertEqual(
            "dispatch",
            self.controller.on_idle(now=13, probe=lambda *args: None).action,
        )
        latest_commit = self.controller.verify_switch(
            latest, evidence(self.c, self.session, 14, ticket=latest), now=14
        )
        self.assertEqual("committed", latest_commit.action)
        self.assertEqual("c", self.controller.actual.alias)
        self.assertEqual("c", self.controller.desired)

    def test_new_probe_failure_does_not_hide_active_verification(self):
        first = self.begin("b", now=10)
        self.controller.finish_probe(
            first,
            evidence(self.b, self.session, 10, ticket=first),
            busy=False,
            now=10,
        )
        latest = self.begin("c", now=11)
        failed = self.controller.finish_probe(
            latest,
            TypedFailure(FailureKind.RATE_LIMITED, "quota", 5),
            busy=False,
            now=11,
        )
        self.assertEqual("rejected", failed.action)
        self.assertEqual(State.VERIFYING, self.controller.state)
        settled = self.controller.verify_switch(
            first, evidence(self.b, self.session, 12, ticket=first), now=12
        )
        self.assertEqual("committed", settled.action)
        self.assertEqual("b", self.controller.actual.alias)

    def test_repeated_target_is_satisfied_by_active_switch(self):
        first = self.begin("b", now=10)
        self.controller.finish_probe(
            first,
            evidence(self.b, self.session, 10, ticket=first),
            busy=False,
            now=10,
        )
        repeated = self.begin("b", now=11)
        self.controller.finish_probe(
            repeated,
            evidence(self.b, self.session, 11, ticket=repeated),
            busy=False,
            now=11,
        )
        self.controller.verify_switch(
            first, evidence(self.b, self.session, 12, ticket=first), now=12
        )
        self.assertIsNone(self.controller.pending)
        self.assertEqual(State.READY, self.controller.state)
        late = self.controller.finish_probe(
            repeated,
            evidence(self.b, self.session, 13, ticket=repeated),
            busy=False,
            now=13,
        )
        self.assertEqual("superseded", late.action)

    def test_selecting_actual_route_cancels_probe_in_flight(self):
        old_ticket = self.begin("b", now=10)
        cancelled = self.begin("a", now=11)
        late = self.controller.finish_probe(
            old_ticket,
            evidence(self.b, self.session, 12, ticket=old_ticket),
            busy=False,
            now=12,
        )
        self.assertEqual("cancelled", cancelled.action)
        self.assertEqual("superseded", late.action)

    def test_old_unexpired_evidence_cannot_verify_new_switch(self):
        ticket = self.begin("b", now=15)
        self.controller.finish_probe(
            ticket,
            evidence(self.b, self.session, 15, ticket=ticket),
            busy=False,
            now=15,
        )
        stale = evidence(self.b, self.session, 1, ticket=ticket, ttl=30)
        result = self.controller.verify_switch(ticket, stale, now=16)
        self.assertEqual("rollback_required", result.action)
        self.assertIn("evidence_predates_action", result.reason)
        self.assertEqual("a", self.controller.desired)

    def test_wrong_correlation_cannot_verify_switch(self):
        ticket = self.begin("b")
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        wrong = evidence(self.b, self.session, 11, ticket=ticket)
        wrong = RouteEvidence(**{**wrong.__dict__, "correlation_id": "old-transaction"})
        result = self.controller.verify_switch(ticket, wrong, now=11)
        self.assertEqual("rollback_required", result.action)
        self.assertIn("evidence_correlation_mismatch", result.reason)

    def test_wrong_revision_cannot_verify_switch(self):
        ticket = self.begin("b")
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        wrong = evidence(self.b, self.session, 11, ticket=ticket)
        wrong = RouteEvidence(**{**wrong.__dict__, "switch_revision": 999})
        result = self.controller.verify_switch(ticket, wrong, now=11)
        self.assertEqual("rollback_required", result.action)
        self.assertIn("evidence_revision_mismatch", result.reason)

    def test_failed_switch_and_failed_rollback_become_degraded(self):
        ticket = self.begin("b")
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        rollback = self.controller.verify_switch(ticket, None, now=11)
        self.assertEqual("rollback_required", rollback.action)
        result = self.controller.verify_rollback(ticket, None, now=12)
        self.assertEqual("degraded", result.action)
        self.assertEqual(State.DEGRADED, self.controller.state)
        self.assertIsNone(self.controller.actual)
        self.assertEqual("a", self.controller.desired)

    def test_verified_rollback_preserves_previous_desired_route(self):
        ticket = self.begin("b")
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        self.controller.verify_switch(ticket, None, now=11)
        result = self.controller.verify_rollback(
            ticket, evidence(self.a, self.session, 12, ticket=ticket), now=12
        )
        self.assertEqual("rolled_back", result.action)
        self.assertEqual("a", self.controller.actual.alias)
        self.assertEqual("a", self.controller.desired)
        self.assertEqual([], self.store.writes)

    def test_new_choice_waits_while_rollback_is_verified(self):
        first = self.begin("b", now=10)
        self.controller.finish_probe(
            first,
            evidence(self.b, self.session, 10, ticket=first),
            busy=False,
            now=10,
        )
        self.controller.verify_switch(first, None, now=11)

        latest = self.begin("c", now=12)
        self.assertEqual(State.ROLLING_BACK, self.controller.state)
        self.controller.finish_probe(
            latest,
            evidence(self.c, self.session, 12, ticket=latest),
            busy=False,
            now=12,
        )
        self.assertEqual(State.ROLLING_BACK, self.controller.state)
        rolled_back = self.controller.verify_rollback(
            first, evidence(self.a, self.session, 13, ticket=first), now=13
        )
        self.assertEqual("rolled_back", rolled_back.action)
        self.assertEqual(State.QUEUED, self.controller.state)
        self.assertEqual(
            "dispatch",
            self.controller.on_idle(now=14, probe=lambda *args: None).action,
        )

    def test_context_and_capabilities_are_preflighted(self):
        too_large = self.controller.begin(
            "b",
            session_id=self.session,
            transcript_tokens=98_000,
            reserved_output_tokens=2_000,
            now=10,
        )
        missing = self.controller.begin(
            "b",
            session_id=self.session,
            transcript_tokens=1,
            reserved_output_tokens=1,
            required_capabilities=frozenset({"images"}),
            now=10,
        )
        hidden_overhead = self.controller.begin(
            "b",
            session_id=self.session,
            transcript_tokens=80_000,
            tool_schema_tokens=10_000,
            control_tokens=5_000,
            reserved_output_tokens=5_000,
            now=10,
        )
        invalid = self.controller.begin(
            "b",
            session_id=self.session,
            transcript_tokens=-1,
            reserved_output_tokens=1,
            now=10,
        )
        self.assertEqual("context_would_not_fit", too_large.reason)
        self.assertEqual("context_would_not_fit", hidden_overhead.reason)
        self.assertEqual("invalid_token_estimate", invalid.reason)
        self.assertEqual("missing_capabilities:images", missing.reason)

    def test_rejected_choice_does_not_supersede_valid_transaction(self):
        ticket = self.begin("b")
        rejected = self.controller.begin(
            "missing",
            session_id=self.session,
            transcript_tokens=1,
            reserved_output_tokens=1,
            now=11,
        )
        result = self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 12, ticket=ticket), busy=False, now=12
        )
        self.assertEqual("rejected", rejected.action)
        self.assertEqual("dispatch", result.action)

    def test_selecting_actual_route_cancels_pending_switch(self):
        ticket = self.begin("b")
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=True, now=10
        )
        cancelled = self.begin("a", now=11)
        self.assertEqual("cancelled", cancelled.action)
        self.assertIsNone(self.controller.pending)
        self.assertEqual("noop", self.controller.on_idle(now=12, probe=lambda *args: None).action)

    def test_typed_failure_creates_and_expires_negative_cache(self):
        ticket = self.begin("b", now=10)
        failure = TypedFailure(FailureKind.RATE_LIMITED, "quota", 5)
        result = self.controller.finish_probe(ticket, failure, busy=False, now=10)
        blocked = self.begin("b", now=12)
        available = self.begin("b", now=16)
        self.assertEqual("rejected", result.action)
        self.assertIn("unavailable:rate_limited", blocked.reason)
        self.assertIsInstance(available, Ticket)

    def test_verification_failure_also_creates_negative_cache(self):
        ticket = self.begin("b", now=10)
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        rollback = self.controller.verify_switch(
            ticket,
            TypedFailure(FailureKind.RATE_LIMITED, "quota", 5),
            now=11,
        )
        self.assertEqual("rollback_required", rollback.action)
        blocked = self.begin("b", now=12)
        self.assertIn("unavailable:rate_limited", blocked.reason)

    def test_non_finite_or_future_evidence_fails_closed(self):
        ticket = self.begin("b", now=10)
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        future = evidence(self.b, self.session, 12, ticket=ticket)
        result = self.controller.verify_switch(ticket, future, now=11)
        self.assertIn("evidence_from_future", result.reason)

    def test_non_finite_probe_evidence_fails_closed(self):
        ticket = self.begin("b", now=10)
        invalid = evidence(self.b, self.session, float("nan"), ticket=ticket)
        result = self.controller.finish_probe(ticket, invalid, busy=False, now=10)
        self.assertEqual("rejected", result.action)
        self.assertEqual("evidence_time_invalid", result.reason)

    def test_failure_without_retry_window_is_not_cached(self):
        ticket = self.begin("b", now=10)
        failure = TypedFailure(FailureKind.TRANSPORT_FAILURE, "connection_reset")
        self.controller.finish_probe(ticket, failure, busy=False, now=10)
        self.assertIsInstance(self.begin("b", now=11), Ticket)

    def test_persistence_failure_reports_degraded_without_losing_actual(self):
        controller = SwitchController(
            {"a": self.a, "b": self.b},
            desired="a",
            actual=self.a_actual,
            state_store=FailingStore("a"),
        )
        ticket = controller.begin(
            "b",
            session_id=self.session,
            transcript_tokens=1,
            reserved_output_tokens=1,
            now=10,
        )
        controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ticket=ticket), busy=False, now=10
        )
        result = controller.verify_switch(
            ticket, evidence(self.b, self.session, 11, ticket=ticket), now=11
        )
        self.assertEqual("degraded", result.action)
        self.assertEqual("persistence_failed", result.reason)
        self.assertEqual("b", controller.actual.alias)
        self.assertEqual("a", controller.desired)

    def test_unknown_persisted_desired_alias_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "not in the registry"):
            SwitchController(
                {"a": self.a},
                actual=self.a_actual,
                state_store=MemoryStateStore("removed-route"),
            )


if __name__ == "__main__":
    unittest.main()
