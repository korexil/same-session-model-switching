import json
import tempfile
import unittest
from pathlib import Path

from state_store import JsonStateStore
from switch_controller import RouteEvidence


class JsonStateStoreTests(unittest.TestCase):
    def test_atomic_store_round_trip(self):
        route_evidence = RouteEvidence(
            alias="route-b",
            provider="provider-b",
            upstream_model="model-b",
            transport="gateway",
            session_id="session-1",
            request_id="request-1",
            switch_revision=4,
            correlation_id="correlation-1",
            observed_at=10,
            expires_at=40,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "desired.json"
            store = JsonStateStore(path)
            self.assertIsNone(store.load_desired())
            store.save_desired("route-b", route_evidence)
            self.assertEqual("route-b", store.load_desired())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("correlation-1", data["committed_from"]["correlation_id"])
            self.assertEqual([], list(path.parent.glob("*.tmp")))

    def test_invalid_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "desired.json"
            path.write_text('{"desired": 42}', encoding="utf-8")
            with self.assertRaises(ValueError):
                JsonStateStore(path).load_desired()


if __name__ == "__main__":
    unittest.main()
