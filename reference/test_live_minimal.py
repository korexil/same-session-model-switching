import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "live-minimal" / "live_minimal.py"
SPEC = importlib.util.spec_from_file_location("live_minimal", SCRIPT)
live_minimal = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = live_minimal
SPEC.loader.exec_module(live_minimal)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def config():
    return live_minimal.LiveConfig(
        gateway_url="http://127.0.0.1:8317/v1/messages",
        gateway_token="secret-never-emit",
        gateway_version="gateway 1.2.3 (abc123)",
        route_a="route-a-model",
        route_a_expected_model="route-a-model",
        claude_bin="claude",
        claude_model="route-b-model",
        claude_expected_model="route-b-model",
        claude_expected_version="2.1.259 (Claude Code)",
        max_budget_usd="0.05",
    )


class LiveMinimalTests(unittest.TestCase):
    def test_verified_receipt_is_bound_to_exact_harness(self):
        receipt_path = SCRIPT.with_name("verified-2026-09-07.json")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        self.assertEqual("PASS", receipt["result"])
        self.assertEqual(digest, receipt["environment"]["harness_sha256"])

    def test_check_mode_is_explicitly_offline(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertIn("no_requests=true", result.stdout)
        self.assertIn("credentials_read=false", result.stdout)

    def test_remote_plain_http_is_rejected(self):
        with self.assertRaisesRegex(live_minimal.LiveFailure, "remote_plain_http_rejected"):
            live_minimal.messages_url("http://gateway.example")

    @patch.object(live_minimal.urllib.request, "urlopen")
    def test_gateway_call_keeps_token_out_of_evidence(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse(
            {
                "id": "request-private",
                "model": "route-a-model",
                "content": [{"type": "thinking", "thinking": "private"}, {"type": "text", "text": "READY"}],
                "usage": {"input_tokens": 3, "output_tokens": 1},
            }
        )
        turn = live_minimal.gateway_turn(config(), [{"role": "user", "content": "synthetic"}])
        self.assertEqual("READY", turn.text)
        self.assertNotEqual("request-private", turn.request_id_hash)
        self.assertNotIn("secret-never-emit", repr(turn))
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual("secret-never-emit", request.headers["X-api-key"])

    def test_claude_command_disables_stateful_customizations(self):
        command = live_minimal.claude_command(config(), "synthetic prompt")
        for flag in (
            "--safe-mode",
            "--restricted",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--no-chrome",
        ):
            self.assertIn(flag, command)
        self.assertEqual("Read", command[command.index("--tools") + 1])
        self.assertNotIn("secret-never-emit", command)

    def test_live_sequence_proves_transcript_workspace_and_return(self):
        calls = []

        def fake_gateway(_config, messages):
            calls.append(messages)
            markers = [word.rstrip(".") for word in " ".join(item["content"] for item in messages).split() if len(word.rstrip(".")) == 24]
            text = "READY" if len(calls) == 1 else " ".join(markers[-2:])
            return live_minimal.GatewayTurn(text, "route-a-model", "abc123", ("text",), 1, 1)

        def fake_claude(_config, prompt, workspace):
            workspace_marker = (workspace / "marker.txt").read_text(encoding="utf-8").strip()
            transcript_marker = next(word.rstrip(".") for word in prompt.split() if len(word.rstrip(".")) == 24)
            return live_minimal.ClaudeTurn(
                transcript_marker + " " + workspace_marker,
                "2.1.259 (Claude Code)",
                ("route-b-model",),
                "def456",
                2,
            )

        receipt = live_minimal.run_live(config(), fake_gateway, fake_claude)
        self.assertEqual("PASS", receipt["result"])
        self.assertTrue(receipt["assertions"]["workspace_read_tool_verified"])
        encoded = json.dumps(receipt)
        self.assertNotIn("secret-never-emit", encoded)
        self.assertNotIn("127.0.0.1", encoded)

    def test_missing_live_configuration_fails_closed(self):
        with self.assertRaisesRegex(live_minimal.LiveFailure, "missing_required_environment"):
            live_minimal.config_from_env({})


if __name__ == "__main__":
    unittest.main()
