import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from http_bridge import HttpBridge
from http_demo import run_demo
from mock_bridge import MockBridgeState, running_mock_bridge
from switch_controller import FailureKind, ModelEntry, RouteEvidence, Ticket, TypedFailure


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def ticket() -> Ticket:
    return Ticket(
        revision=7,
        correlation_id="switch-7-unique",
        session_id="session-1",
        target=ModelEntry(
            alias="route-b",
            provider="provider-b",
            upstream_model="model-b",
            transport="gateway-b",
            context_window=100_000,
            capabilities=frozenset({"tools"}),
        ),
        requested_at=10.0,
    )


class HttpBridgeTests(unittest.TestCase):
    def test_remote_plain_http_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            HttpBridge("http://bridge.example")

    @patch("http_bridge.urlopen")
    def test_probe_preserves_causal_fields(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse(
            {
                "evidence": {
                    "alias": "route-b",
                    "provider": "provider-b",
                    "upstream_model": "model-b",
                    "transport": "gateway-b",
                    "session_id": "session-1",
                    "request_id": "request-9",
                    "switch_revision": 7,
                    "correlation_id": "switch-7-unique",
                    "observed_at": 11,
                    "expires_at": 21,
                }
            }
        )
        result = HttpBridge("http://127.0.0.1:9000", token="not-logged").probe(ticket())
        self.assertIsInstance(result, RouteEvidence)
        self.assertEqual(7, result.switch_revision)
        self.assertEqual("switch-7-unique", result.correlation_id)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual("Bearer not-logged", request.headers["Authorization"])

    @patch("http_bridge.urlopen")
    def test_typed_failure_is_normalized(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse(
            {
                "failure": {
                    "kind": "rate_limited",
                    "safe_reason": "quota_exhausted",
                    "retry_after_seconds": 30,
                }
            }
        )
        result = HttpBridge("http://localhost:9000").probe(ticket())
        self.assertEqual(
            TypedFailure(FailureKind.RATE_LIMITED, "quota_exhausted", 30.0), result
        )

    @patch("http_bridge.urlopen")
    def test_dispatch_requires_explicit_acceptance(self, mocked_urlopen):
        bridge = HttpBridge("https://bridge.example")
        mocked_urlopen.return_value = FakeResponse({"accepted": True})
        self.assertIsNone(bridge.dispatch(ticket()))
        mocked_urlopen.return_value = FakeResponse({"accepted": False})
        self.assertEqual(FailureKind.PROTOCOL_VIOLATION, bridge.dispatch(ticket()).kind)

    @patch("http_bridge.urlopen")
    def test_rollback_can_target_previous_route_in_same_transaction(self, mocked_urlopen):
        previous = ModelEntry(
            alias="route-a",
            provider="provider-a",
            upstream_model="model-a",
            transport="gateway-a",
            context_window=100_000,
            capabilities=frozenset({"tools"}),
        )
        mocked_urlopen.return_value = FakeResponse({"accepted": True})
        bridge = HttpBridge("https://bridge.example")
        self.assertIsNone(bridge.dispatch(ticket(), route=previous, phase="rollback"))
        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual("rollback", payload["phase"])
        self.assertEqual("route-a", payload["route"]["alias"])
        self.assertEqual(7, payload["switch_revision"])
        self.assertEqual("switch-7-unique", payload["correlation_id"])

    @patch("http_bridge.urlopen")
    def test_invalid_evidence_fails_closed(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse({"evidence": {"alias": "route-b"}})
        result = HttpBridge("https://bridge.example").observe(ticket())
        self.assertEqual(FailureKind.PROTOCOL_VIOLATION, result.kind)

    @patch("http_bridge.urlopen")
    def test_http_rate_limit_preserves_retry_window(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            "https://bridge.example/v1/probe",
            429,
            "rate limited",
            {"Retry-After": "12"},
            None,
        )
        result = HttpBridge("https://bridge.example").probe(ticket())
        self.assertEqual(FailureKind.RATE_LIMITED, result.kind)
        self.assertEqual(12.0, result.retry_after_seconds)

    def test_runnable_bridge_crosses_http_and_preserves_session(self):
        result = run_demo(show_receipts=False)
        self.assertTrue(result["same_session"])
        self.assertTrue(result["workspace_preserved"])
        self.assertTrue(result["exact_session_evidence"])

    def test_mock_bridge_rejects_evidence_before_dispatch(self):
        target = ticket()
        state = MockBridgeState(
            {target.target.alias: target.target},
            {target.session_id: target.target.alias},
        )
        with running_mock_bridge(state) as base_url:
            result = HttpBridge(base_url).observe(target)
        self.assertIsInstance(result, TypedFailure)
        self.assertEqual(FailureKind.PROTOCOL_VIOLATION, result.kind)
        self.assertEqual("switch_transaction_not_observed", result.safe_reason)


if __name__ == "__main__":
    unittest.main()
