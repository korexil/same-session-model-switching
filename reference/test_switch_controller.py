import unittest

from switch_controller import ModelEntry, RouteEvidence, State, SwitchController


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


def evidence(model: ModelEntry, session: str, now: float, ttl: float = 30) -> RouteEvidence:
    return RouteEvidence(
        alias=model.alias,
        provider=model.provider,
        upstream_model=model.upstream_model,
        transport=model.transport,
        session_id=session,
        request_id=f"request-{model.alias}-{now}",
        observed_at=now,
        expires_at=now + ttl,
    )


class SwitchControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = entry("a")
        self.b = entry("b")
        self.session = "session-under-test"
        self.a_actual = evidence(self.a, self.session, 0, ttl=1_000)
        self.controller = SwitchController(
            {"a": self.a, "b": self.b}, desired="a", actual=self.a_actual
        )

    def begin(self, alias: str):
        return self.controller.begin(
            alias,
            session_id=self.session,
            transcript_tokens=10_000,
            reserved_output_tokens=2_000,
            required_capabilities=frozenset({"tools"}),
        )

    def test_happy_path_commits_only_after_route_verification(self):
        ticket = self.begin("b")
        decision = self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10), busy=False, now=10
        )
        self.assertEqual("dispatch", decision.action)
        self.assertEqual("a", self.controller.desired)

        result = self.controller.verify_switch(
            ticket, evidence(self.b, self.session, 11), now=11
        )
        self.assertEqual("committed", result.action)
        self.assertEqual("b", self.controller.desired)
        self.assertEqual("b", self.controller.actual.alias)

    def test_busy_queue_reprobes_expired_evidence(self):
        ticket = self.begin("b")
        queued = self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10, ttl=2), busy=True, now=10
        )
        self.assertEqual("queued", queued.action)

        calls = []

        def reprobe(model, session, revision, now):
            calls.append((model.alias, session, revision))
            return evidence(model, session, now)

        decision = self.controller.on_idle(now=20, probe=reprobe)
        self.assertEqual("dispatch", decision.action)
        self.assertEqual([("b", self.session, ticket.revision)], calls)

    def test_slow_old_probe_cannot_override_latest_choice(self):
        old_ticket = self.begin("b")
        new_ticket = self.begin("a")

        old_result = self.controller.finish_probe(
            old_ticket, evidence(self.b, self.session, 10), busy=False, now=10
        )
        new_result = self.controller.finish_probe(
            new_ticket, evidence(self.a, self.session, 11), busy=False, now=11
        )
        self.assertEqual("superseded", old_result.action)
        self.assertEqual("dispatch", new_result.action)

    def test_failed_switch_and_failed_rollback_become_degraded(self):
        ticket = self.begin("b")
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10), busy=False, now=10
        )

        rollback = self.controller.verify_switch(
            ticket, evidence(self.a, self.session, 11), now=11
        )
        self.assertEqual("rollback_required", rollback.action)
        self.assertEqual("a", rollback.target)

        result = self.controller.verify_rollback(ticket, None, now=12)
        self.assertEqual("degraded", result.action)
        self.assertEqual(State.DEGRADED, self.controller.state)
        self.assertIsNone(self.controller.actual)
        self.assertEqual("a", self.controller.desired)

    def test_verified_rollback_preserves_previous_route(self):
        ticket = self.begin("b")
        self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10), busy=False, now=10
        )
        self.controller.verify_switch(ticket, None, now=11)
        result = self.controller.verify_rollback(
            ticket, evidence(self.a, self.session, 12), now=12
        )
        self.assertEqual("rolled_back", result.action)
        self.assertEqual("a", self.controller.actual.alias)
        self.assertEqual("a", self.controller.desired)

    def test_context_and_capabilities_are_preflighted(self):
        too_large = self.controller.begin(
            "b",
            session_id=self.session,
            transcript_tokens=98_000,
            reserved_output_tokens=2_000,
        )
        missing = self.controller.begin(
            "b",
            session_id=self.session,
            transcript_tokens=1,
            reserved_output_tokens=1,
            required_capabilities=frozenset({"images"}),
        )
        self.assertEqual("context_would_not_fit", too_large.reason)
        self.assertEqual("missing_capabilities:images", missing.reason)

    def test_rejected_choice_does_not_supersede_valid_transaction(self):
        ticket = self.begin("b")
        rejected = self.controller.begin(
            "missing",
            session_id=self.session,
            transcript_tokens=1,
            reserved_output_tokens=1,
        )
        result = self.controller.finish_probe(
            ticket, evidence(self.b, self.session, 10), busy=False, now=10
        )
        self.assertEqual("rejected", rejected.action)
        self.assertEqual("dispatch", result.action)


if __name__ == "__main__":
    unittest.main()
