import unittest

from context_planner import (
    ContextAction,
    ContextLoad,
    RouteWindow,
    plan_context_transition,
)


class ContextPlannerTests(unittest.TestCase):
    def test_switches_directly_when_target_fits(self):
        plan = plan_context_transition(
            current=RouteWindow("large", 200_000),
            target=RouteWindow("medium", 128_000),
            load=ContextLoad(80_000, tool_schema_tokens=4_000),
            compacted_total_tokens=30_000,
        )
        self.assertEqual(plan.action, ContextAction.SWITCH_DIRECT)

    def test_compacts_on_current_route_before_downshift(self):
        plan = plan_context_transition(
            current=RouteWindow("large", 200_000),
            target=RouteWindow("small", 64_000),
            load=ContextLoad(90_000),
            compacted_total_tokens=40_000,
        )
        self.assertEqual(plan.action, ContextAction.COMPACT_CURRENT_THEN_SWITCH)
        self.assertEqual(plan.recovery_alias, "large")

    def test_uses_reachable_recovery_route_when_current_cannot_compact(self):
        plan = plan_context_transition(
            current=RouteWindow("exhausted", 200_000, reachable=False),
            target=RouteWindow("small", 64_000),
            load=ContextLoad(90_000),
            compacted_total_tokens=40_000,
            recovery_routes=(RouteWindow("recovery", 128_000),),
        )
        self.assertEqual(plan.action, ContextAction.SWITCH_RECOVERY_THEN_COMPACT)
        self.assertEqual(plan.recovery_alias, "recovery")

    def test_requires_handoff_when_compacted_context_still_does_not_fit(self):
        plan = plan_context_transition(
            current=RouteWindow("large", 200_000),
            target=RouteWindow("tiny", 32_000),
            load=ContextLoad(90_000),
            compacted_total_tokens=30_000,
        )
        self.assertEqual(plan.action, ContextAction.START_NEW_SESSION_WITH_HANDOFF)

    def test_requires_handoff_when_no_route_can_carry_raw_context(self):
        plan = plan_context_transition(
            current=RouteWindow("offline", 200_000, reachable=False),
            target=RouteWindow("small", 64_000),
            load=ContextLoad(90_000),
            compacted_total_tokens=40_000,
            recovery_routes=(RouteWindow("too-small", 80_000),),
        )
        self.assertEqual(plan.action, ContextAction.START_NEW_SESSION_WITH_HANDOFF)


if __name__ == "__main__":
    unittest.main()
