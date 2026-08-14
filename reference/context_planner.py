"""Pure planning for context-safe same-session route changes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional


class ContextAction(str, Enum):
    SWITCH_DIRECT = "switch_direct"
    COMPACT_CURRENT_THEN_SWITCH = "compact_current_then_switch"
    SWITCH_RECOVERY_THEN_COMPACT = "switch_recovery_then_compact"
    START_NEW_SESSION_WITH_HANDOFF = "start_new_session_with_handoff"


@dataclass(frozen=True)
class RouteWindow:
    alias: str
    context_window: int
    safety_margin_tokens: int = 8_192
    reachable: bool = True

    @property
    def usable_tokens(self) -> int:
        return self.context_window - self.safety_margin_tokens


@dataclass(frozen=True)
class ContextLoad:
    transcript_tokens: int
    tool_schema_tokens: int = 0
    control_tokens: int = 0
    reserved_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        values = (
            self.transcript_tokens,
            self.tool_schema_tokens,
            self.control_tokens,
            self.reserved_output_tokens,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("context token counts must be non-negative integers")
        return sum(values)


@dataclass(frozen=True)
class ContextPlan:
    action: ContextAction
    reason: str
    required_tokens: int
    target_usable_tokens: int
    recovery_alias: Optional[str] = None


def plan_context_transition(
    *,
    current: RouteWindow,
    target: RouteWindow,
    load: ContextLoad,
    compacted_total_tokens: Optional[int],
    recovery_routes: Iterable[RouteWindow] = (),
) -> ContextPlan:
    """Choose the least lossy safe path; never invent a larger model window."""

    required = load.total_tokens
    _validate_route(current)
    _validate_route(target)
    recovery = tuple(recovery_routes)
    for route in recovery:
        _validate_route(route)

    if target.reachable and required <= target.usable_tokens:
        return ContextPlan(
            ContextAction.SWITCH_DIRECT,
            "current_context_fits_target",
            required,
            target.usable_tokens,
        )

    if (
        compacted_total_tokens is None
        or not isinstance(compacted_total_tokens, int)
        or isinstance(compacted_total_tokens, bool)
        or compacted_total_tokens < 0
        or not target.reachable
        or compacted_total_tokens > target.usable_tokens
    ):
        return ContextPlan(
            ContextAction.START_NEW_SESSION_WITH_HANDOFF,
            "target_cannot_accept_verified_compacted_context",
            required,
            target.usable_tokens,
        )

    if current.reachable and required <= current.usable_tokens:
        return ContextPlan(
            ContextAction.COMPACT_CURRENT_THEN_SWITCH,
            "compact_while_current_route_still_carries_full_context",
            required,
            target.usable_tokens,
            current.alias,
        )

    candidates = sorted(
        (
            route
            for route in recovery
            if route.reachable and required <= route.usable_tokens
        ),
        key=lambda route: (route.usable_tokens, route.alias),
    )
    if candidates:
        route = candidates[0]
        return ContextPlan(
            ContextAction.SWITCH_RECOVERY_THEN_COMPACT,
            "current_route_unavailable_or_too_small_for_compaction",
            required,
            target.usable_tokens,
            route.alias,
        )

    return ContextPlan(
        ContextAction.START_NEW_SESSION_WITH_HANDOFF,
        "no_reachable_route_can_carry_the_uncompacted_context",
        required,
        target.usable_tokens,
    )


def _validate_route(route: RouteWindow) -> None:
    if not route.alias:
        raise ValueError("route alias is required")
    values = (route.context_window, route.safety_margin_tokens)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        raise ValueError("route window values must be non-negative integers")
    if route.usable_tokens <= 0:
        raise ValueError("route safety margin leaves no usable context")
