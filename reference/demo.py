"""Run a credential-free A -> B -> A same-session switching demonstration."""

from __future__ import annotations

from dataclasses import dataclass, field

from switch_controller import ModelEntry, RouteEvidence, SwitchController, Ticket


@dataclass
class DemoShell:
    session_id: str
    route: ModelEntry
    transcript: list[tuple[str, str]] = field(default_factory=list)
    workspace: dict[str, str] = field(default_factory=dict)
    clock: float = 1.0

    def reply(self, user_text: str) -> None:
        self.transcript.append(("user", user_text))
        self.transcript.append(
            ("assistant", f"{self.route.alias} received message {len(self.transcript) // 2}")
        )

    def route_evidence(self) -> RouteEvidence:
        self.clock += 1
        return RouteEvidence(
            alias=self.route.alias,
            provider=self.route.provider,
            upstream_model=self.route.upstream_model,
            transport=self.route.transport,
            session_id=self.session_id,
            request_id=f"demo-{int(self.clock)}",
            observed_at=self.clock,
            expires_at=self.clock + 30,
        )


def model(alias: str) -> ModelEntry:
    return ModelEntry(
        alias=alias,
        provider=f"demo-provider-{alias}",
        upstream_model=f"demo-model-{alias}",
        transport="in-memory-demo",
        context_window=100_000,
        capabilities=frozenset({"streaming", "tools"}),
        safety_margin_tokens=1_000,
    )


def switch(shell: DemoShell, controller: SwitchController, target: str) -> None:
    ticket = controller.begin(
        target,
        session_id=shell.session_id,
        transcript_tokens=len(str(shell.transcript)),
        reserved_output_tokens=1_000,
        required_capabilities=frozenset({"tools"}),
    )
    assert isinstance(ticket, Ticket)

    probe = RouteEvidence(
        alias=ticket.target.alias,
        provider=ticket.target.provider,
        upstream_model=ticket.target.upstream_model,
        transport=ticket.target.transport,
        session_id=shell.session_id,
        request_id=f"probe-{ticket.revision}",
        observed_at=shell.clock,
        expires_at=shell.clock + 30,
    )
    assert controller.finish_probe(ticket, probe, busy=False, now=shell.clock).action == "dispatch"

    # The route event is control-plane evidence; it is not inserted as a fake
    # user message in the conversation transcript.
    shell.route = ticket.target
    assert controller.verify_switch(ticket, shell.route_evidence(), now=shell.clock).action == "committed"


def main() -> None:
    route_a, route_b = model("route-a"), model("route-b")
    shell = DemoShell("demo-session-001", route_a)
    controller = SwitchController(
        {route_a.alias: route_a, route_b.alias: route_b},
        desired=route_a.alias,
        actual=shell.route_evidence(),
    )

    shell.workspace["shared.txt"] = "written before switching"
    shell.reply("first message")
    switch(shell, controller, route_b.alias)
    shell.reply("second message")
    switch(shell, controller, route_a.alias)
    shell.reply("third message")

    assert shell.session_id == "demo-session-001"
    assert len(shell.transcript) == 6
    assert shell.workspace["shared.txt"] == "written before switching"
    assert controller.actual is not None and controller.actual.alias == route_a.alias
    print(
        "PASS same_session=true route_sequence=route-a>route-b>route-a "
        "transcript_messages=6 workspace_preserved=true"
    )


if __name__ == "__main__":
    main()
