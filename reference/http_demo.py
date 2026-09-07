"""Exercise A -> B -> A across the real JSON/HTTP bridge boundary."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from http_bridge import HttpBridge
from mock_bridge import MockBridgeState, running_mock_bridge
from switch_controller import ModelEntry, RouteEvidence, SwitchController, Ticket


@dataclass
class DemoShell:
    session_id: str
    transcript: list[tuple[str, str]] = field(default_factory=list)
    workspace: dict[str, str] = field(default_factory=dict)

    def reply(self, route_alias: str, user_text: str) -> None:
        self.transcript.append(("user", user_text))
        self.transcript.append(
            ("assistant", f"{route_alias} received message {len(self.transcript) // 2}")
        )


def model(alias: str) -> ModelEntry:
    return ModelEntry(
        alias=alias,
        provider=f"demo-provider-{alias}",
        upstream_model=f"demo-model-{alias}",
        transport="loopback-http-demo",
        context_window=100_000,
        capabilities=frozenset({"streaming", "tools"}),
        safety_margin_tokens=1_000,
    )


def initial_evidence(route: ModelEntry, session_id: str) -> RouteEvidence:
    now = time.time()
    return RouteEvidence(
        alias=route.alias,
        provider=route.provider,
        upstream_model=route.upstream_model,
        transport=route.transport,
        session_id=session_id,
        request_id="mock-initial-route",
        switch_revision=0,
        correlation_id="mock-initial-route",
        observed_at=now,
        expires_at=now + 30,
    )


def switch_over_http(
    shell: DemoShell,
    controller: SwitchController,
    bridge: HttpBridge,
    target_alias: str,
) -> RouteEvidence:
    ticket = controller.begin(
        target_alias,
        session_id=shell.session_id,
        transcript_tokens=len(str(shell.transcript)),
        reserved_output_tokens=1_000,
        required_capabilities=frozenset({"tools"}),
        now=time.time(),
    )
    assert isinstance(ticket, Ticket)
    probe = bridge.probe(ticket)
    assert controller.finish_probe(
        ticket, probe, busy=False, now=time.time()
    ).action == "dispatch"
    dispatch_failure = bridge.dispatch(ticket)
    if dispatch_failure is not None:
        raise RuntimeError(dispatch_failure.safe_reason)
    observed = bridge.observe(ticket)
    decision = controller.verify_switch(ticket, observed, now=time.time())
    if decision.action != "committed" or not isinstance(observed, RouteEvidence):
        raise RuntimeError(decision.reason or decision.action)
    return observed


def run_demo(*, show_receipts: bool = True) -> dict[str, object]:
    route_a, route_b = model("route-a"), model("route-b")
    routes = {route_a.alias: route_a, route_b.alias: route_b}
    shell = DemoShell("demo-session-001")
    state = MockBridgeState(routes, {shell.session_id: route_a.alias})
    controller = SwitchController(
        routes,
        desired=route_a.alias,
        actual=initial_evidence(route_a, shell.session_id),
    )

    shell.workspace["shared.txt"] = "written before switching"
    shell.reply(state.current_alias(shell.session_id) or "unknown", "first message")
    receipts: list[RouteEvidence] = []
    with running_mock_bridge(state) as base_url:
        bridge = HttpBridge(base_url)
        for target, message in ((route_b.alias, "second message"), (route_a.alias, "third message")):
            receipt = switch_over_http(shell, controller, bridge, target)
            receipts.append(receipt)
            if show_receipts:
                print(
                    f"SWITCH revision={receipt.switch_revision} "
                    f"session={receipt.session_id} target={receipt.alias} "
                    f"evidence={receipt.request_id}"
                )
            shell.reply(state.current_alias(shell.session_id) or "unknown", message)

    result = {
        "same_session": all(item.session_id == shell.session_id for item in receipts),
        "route_sequence": "route-a>route-b>route-a",
        "transcript_messages": len(shell.transcript),
        "workspace_preserved": shell.workspace.get("shared.txt")
        == "written before switching",
        "exact_session_evidence": len(receipts) == 2,
        "final_route": controller.actual.alias if controller.actual else None,
    }
    assert result == {
        "same_session": True,
        "route_sequence": "route-a>route-b>route-a",
        "transcript_messages": 6,
        "workspace_preserved": True,
        "exact_session_evidence": True,
        "final_route": "route-a",
    }
    return result


def main() -> None:
    result = run_demo()
    print(
        "PASS same_session=true route_sequence=route-a>route-b>route-a "
        f"transcript_messages={result['transcript_messages']} "
        "workspace_preserved=true transport=http "
        "exact_session_evidence=true"
    )


if __name__ == "__main__":
    main()
