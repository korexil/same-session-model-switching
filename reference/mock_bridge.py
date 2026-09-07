"""Runnable loopback server for rehearsing the live bridge contract."""

from __future__ import annotations

import json
import math
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any, Iterator, Mapping

from switch_controller import FailureKind, ModelEntry


Json = dict[str, Any]


class MockBridgeState:
    """Small fail-closed fake; replace this state with real shell/gateway calls."""

    def __init__(
        self,
        routes: Mapping[str, ModelEntry],
        sessions: Mapping[str, str],
        *,
        evidence_ttl_seconds: float = 30.0,
    ) -> None:
        self.routes = dict(routes)
        self.sessions = dict(sessions)
        self.evidence_ttl_seconds = evidence_ttl_seconds
        self._transactions: dict[tuple[str, int, str, str], str] = {}
        self._request_number = 0
        self._lock = Lock()

    def handle(self, path: str, payload: object) -> Json:
        parsed = self._parse_payload(payload)
        if isinstance(parsed, dict) and "failure" in parsed:
            return parsed
        assert isinstance(parsed, tuple)
        session_id, revision, correlation_id, phase, route = parsed

        expected_phase = "probe" if path == "/v1/probe" else None
        if expected_phase and phase != expected_phase:
            return _failure(FailureKind.PROTOCOL_VIOLATION, "invalid_phase")
        if path in {"/v1/switch", "/v1/evidence"} and phase not in {
            "forward",
            "rollback",
        }:
            return _failure(FailureKind.PROTOCOL_VIOLATION, "invalid_phase")

        transaction = (session_id, revision, correlation_id, phase)
        with self._lock:
            if path == "/v1/switch":
                self.sessions[session_id] = route.alias
                self._transactions[transaction] = route.alias
                return {"accepted": True}
            if path == "/v1/evidence":
                if self._transactions.get(transaction) != route.alias:
                    return _failure(
                        FailureKind.PROTOCOL_VIOLATION,
                        "switch_transaction_not_observed",
                    )
                if self.sessions.get(session_id) != route.alias:
                    return _failure(FailureKind.PROVIDER_FAILURE, "route_not_active")
            elif path != "/v1/probe":
                return _failure(FailureKind.PROTOCOL_VIOLATION, "unknown_endpoint")
            return {"evidence": self._evidence(session_id, revision, correlation_id, route)}

    def current_alias(self, session_id: str) -> str | None:
        with self._lock:
            return self.sessions.get(session_id)

    def _parse_payload(
        self, payload: object
    ) -> tuple[str, int, str, str, ModelEntry] | Json:
        if not isinstance(payload, Mapping):
            return _failure(FailureKind.PROTOCOL_VIOLATION, "invalid_payload")
        session_id = payload.get("session_id")
        revision = payload.get("switch_revision")
        correlation_id = payload.get("correlation_id")
        requested_at = payload.get("requested_at")
        phase = payload.get("phase")
        route_payload = payload.get("route")
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
            or not isinstance(correlation_id, str)
            or not correlation_id
            or not isinstance(requested_at, (int, float))
            or isinstance(requested_at, bool)
            or not math.isfinite(float(requested_at))
            or not isinstance(phase, str)
            or not isinstance(route_payload, Mapping)
        ):
            return _failure(FailureKind.PROTOCOL_VIOLATION, "invalid_payload")

        alias = route_payload.get("alias")
        route = self.routes.get(alias) if isinstance(alias, str) else None
        if route is None:
            return _failure(FailureKind.MODEL_UNKNOWN, "unknown_route")
        expected = {
            "alias": route.alias,
            "provider": route.provider,
            "upstream_model": route.upstream_model,
            "transport": route.transport,
        }
        if any(route_payload.get(key) != value for key, value in expected.items()):
            return _failure(FailureKind.PROTOCOL_VIOLATION, "route_identity_mismatch")
        return session_id, revision, correlation_id, phase, route

    def _evidence(
        self,
        session_id: str,
        revision: int,
        correlation_id: str,
        route: ModelEntry,
    ) -> Json:
        self._request_number += 1
        observed_at = time.time()
        return {
            "alias": route.alias,
            "provider": route.provider,
            "upstream_model": route.upstream_model,
            "transport": route.transport,
            "session_id": session_id,
            "request_id": f"mock-request-{self._request_number}",
            "switch_revision": revision,
            "correlation_id": correlation_id,
            "observed_at": observed_at,
            "expires_at": observed_at + self.evidence_ttl_seconds,
        }


def _failure(kind: FailureKind, reason: str) -> Json:
    return {"failure": {"kind": kind.value, "safe_reason": reason}}


def _handler(state: MockBridgeState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise ValueError("invalid body length")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                response = state.handle(self.path, payload)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                response = _failure(FailureKind.PROTOCOL_VIOLATION, "invalid_json")
            body = json.dumps(response, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


@contextmanager
def running_mock_bridge(state: MockBridgeState) -> Iterator[str]:
    """Run the bridge on an ephemeral loopback port and cleanly stop it."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
