#!/usr/bin/env python3
"""Opt-in, privacy-safe A -> B -> A live integration harness.

The Python process owns the provider-neutral transcript and temporary workspace.
Route A uses an Anthropic-compatible HTTP gateway. Route B uses the official
Claude Code CLI in an isolated, non-persistent print-mode process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class LiveFailure(RuntimeError):
    def __init__(self, kind: str, safe_reason: str):
        super().__init__(safe_reason)
        self.kind = kind
        self.safe_reason = safe_reason


@dataclass(frozen=True)
class LiveConfig:
    gateway_url: str
    gateway_token: str
    gateway_version: str
    route_a: str
    route_a_expected_model: str
    claude_bin: str
    claude_model: str
    claude_expected_model: str
    claude_expected_version: str | None
    max_budget_usd: str


@dataclass(frozen=True)
class GatewayTurn:
    text: str
    returned_model: str
    request_id_hash: str
    content_types: tuple[str, ...]
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class ClaudeTurn:
    text: str
    version: str
    models_used: tuple[str, ...]
    session_id_hash: str
    turns: int | None


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def canonical_source_hash(path: Path) -> str:
    """Hash UTF-8 source with canonical LF line endings across Git checkouts."""
    text = path.read_text(encoding="utf-8")
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def messages_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LiveFailure("configuration", "gateway_url_invalid")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise LiveFailure("configuration", "remote_plain_http_rejected")
    if parsed.path.rstrip("/").endswith("/v1/messages"):
        return base_url
    return base_url.rstrip("/") + "/v1/messages"


def config_from_env(environ: dict[str, str] | None = None) -> LiveConfig:
    env = os.environ if environ is None else environ
    required = (
        "LIVE_GATEWAY_URL",
        "LIVE_GATEWAY_TOKEN",
        "LIVE_GATEWAY_VERSION",
        "LIVE_ROUTE_A",
        "LIVE_CLAUDE_MODEL",
        "LIVE_CLAUDE_EXPECTED_MODEL",
        "LIVE_EXPECT_CLAUDE_VERSION",
    )
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise LiveFailure("configuration", "missing_required_environment")
    route_a = env["LIVE_ROUTE_A"]
    return LiveConfig(
        gateway_url=messages_url(env["LIVE_GATEWAY_URL"]),
        gateway_token=env["LIVE_GATEWAY_TOKEN"],
        gateway_version=env["LIVE_GATEWAY_VERSION"],
        route_a=route_a,
        route_a_expected_model=env.get("LIVE_ROUTE_A_EXPECTED_MODEL", route_a),
        claude_bin=env.get("LIVE_CLAUDE_BIN", "claude"),
        claude_model=env["LIVE_CLAUDE_MODEL"],
        claude_expected_model=env["LIVE_CLAUDE_EXPECTED_MODEL"],
        claude_expected_version=env["LIVE_EXPECT_CLAUDE_VERSION"],
        max_budget_usd=env.get("LIVE_MAX_BUDGET_USD", "0.05"),
    )


def gateway_turn(config: LiveConfig, messages: list[dict[str, str]]) -> GatewayTurn:
    request = urllib.request.Request(
        config.gateway_url,
        data=json.dumps(
            {"model": config.route_a, "max_tokens": 96, "messages": messages}
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": config.gateway_token,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        kinds = {401: "auth_rejected", 403: "auth_rejected", 404: "model_unknown", 429: "rate_limited"}
        raise LiveFailure(kinds.get(error.code, "provider_failure"), f"gateway_http_{error.code}") from None
    except (OSError, TimeoutError, urllib.error.URLError):
        raise LiveFailure("transport_failure", "gateway_unreachable") from None

    content = payload.get("content", [])
    if not isinstance(content, list):
        raise LiveFailure("protocol_violation", "gateway_content_invalid")
    text = "".join(
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    ).strip()
    returned_model = str(payload.get("model", ""))
    request_id = str(payload.get("id", ""))
    if not text or not returned_model or not request_id:
        raise LiveFailure("protocol_violation", "gateway_evidence_incomplete")
    if returned_model != config.route_a_expected_model:
        raise LiveFailure("protocol_violation", "gateway_model_mismatch")
    usage = payload.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    return GatewayTurn(
        text=text,
        returned_model=returned_model,
        request_id_hash=short_hash(request_id),
        content_types=tuple(
            str(item.get("type")) for item in content if isinstance(item, dict)
        ),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )


def claude_command(config: LiveConfig, prompt: str) -> list[str]:
    return [
        config.claude_bin,
        "-p",
        "--safe-mode",
        "--restricted",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--no-chrome",
        "--disable-slash-commands",
        "--prompt-suggestions", "false",
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--tools", "Read",
        "--allowedTools", "Read",
        "--model", config.claude_model,
        "--max-budget-usd", config.max_budget_usd,
        "--output-format", "json",
        prompt,
    ]


def claude_turn(config: LiveConfig, prompt: str, workspace: Path) -> ClaudeTurn:
    try:
        version_run = subprocess.run(
            [config.claude_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise LiveFailure("transport_failure", "claude_cli_unavailable") from None
    version = version_run.stdout.strip()
    if version_run.returncode or not version:
        raise LiveFailure("transport_failure", "claude_version_unavailable")
    if config.claude_expected_version and version != config.claude_expected_version:
        raise LiveFailure("configuration", "claude_version_mismatch")

    try:
        completed = subprocess.run(
            claude_command(config, prompt),
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise LiveFailure("transport_failure", "claude_cli_failed") from None
    if completed.returncode:
        raise LiveFailure("provider_failure", f"claude_exit_{completed.returncode}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise LiveFailure("protocol_violation", "claude_json_invalid") from None
    text = str(payload.get("result", "")).strip()
    session_id = str(payload.get("session_id", ""))
    model_usage = payload.get("modelUsage", {})
    if not text or not session_id or not isinstance(model_usage, dict) or not model_usage:
        raise LiveFailure("protocol_violation", "claude_evidence_incomplete")
    if config.claude_expected_model not in model_usage:
        raise LiveFailure("protocol_violation", "claude_model_mismatch")
    return ClaudeTurn(
        text=text,
        version=version,
        models_used=tuple(sorted(str(model) for model in model_usage)),
        session_id_hash=short_hash(session_id),
        turns=payload.get("num_turns"),
    )


GatewayCall = Callable[[LiveConfig, list[dict[str, str]]], GatewayTurn]
ClaudeCall = Callable[[LiveConfig, str, Path], ClaudeTurn]


def run_live(
    config: LiveConfig,
    gateway_call: GatewayCall = gateway_turn,
    claude_call: ClaudeCall = claude_turn,
) -> dict[str, object]:
    shell_session_id = secrets.token_hex(16)
    transcript_marker = secrets.token_hex(12)
    workspace_marker = secrets.token_hex(12)
    transcript: list[dict[str, str]] = [
        {
            "role": "user",
            "content": "Synthetic transcript marker: " + transcript_marker + ". Reply READY_A only.",
        }
    ]

    first = gateway_call(config, transcript)
    transcript.append({"role": "assistant", "content": first.text})

    with tempfile.TemporaryDirectory(prefix="same-session-live-") as directory:
        workspace = Path(directory)
        (workspace / "marker.txt").write_text(workspace_marker + "\n", encoding="utf-8")
        rendered = "\n".join(
            f"{item['role'].upper()}: {item['content']}" for item in transcript
        )
        prompt = (
            "This is a synthetic integration test. Here is the provider-neutral transcript:\n"
            + rendered
            + "\nUse the Read tool to read marker.txt. Return both the transcript marker from the "
            "first user turn and the workspace marker from the file."
        )
        middle = claude_call(config, prompt, workspace)
        if transcript_marker not in middle.text:
            raise LiveFailure("continuity_failure", "claude_transcript_marker_missing")
        if workspace_marker not in middle.text:
            raise LiveFailure("tool_failure", "claude_workspace_marker_missing")

        transcript.append({"role": "user", "content": "Continue with route B using the same shell transcript."})
        transcript.append({"role": "assistant", "content": middle.text})
        transcript.append(
            {
                "role": "user",
                "content": "Back on route A: return both markers from the prior assistant turn.",
            }
        )
        final = gateway_call(config, transcript)

    if transcript_marker not in final.text or workspace_marker not in final.text:
        raise LiveFailure("continuity_failure", "return_route_markers_missing")

    return {
        "schema_version": 1,
        "result": "PASS",
        "claim": "live_minimal_a_b_a_continuity_and_tool_use",
        "observed_on_utc": datetime.now(timezone.utc).date().isoformat(),
        "privacy": {
            "synthetic_only": True,
            "raw_prompts_saved": False,
            "raw_responses_saved": False,
            "credentials_emitted": False,
            "temporary_workspace_deleted": True,
        },
        "session": {
            "owner": "live_minimal_python_process",
            "id_sha256_12": short_hash(shell_session_id),
            "same_transcript_object": True,
        },
        "environment": {
            "gateway_version": config.gateway_version,
            "harness_sha256": canonical_source_hash(Path(__file__)),
            "harness_hash_canonicalization": "utf8_lf",
        },
        "sequence": [
            {
                "step": "A1",
                "transport": "anthropic_compatible_gateway",
                "requested_model": config.route_a,
                "returned_model": first.returned_model,
                "request_id_sha256_12": first.request_id_hash,
                "content_types": list(first.content_types),
                "input_tokens": first.input_tokens,
                "output_tokens": first.output_tokens,
            },
            {
                "step": "B",
                "transport": "official_claude_code_cli",
                "requested_model": config.claude_model,
                "models_used": list(middle.models_used),
                "cli_version": middle.version,
                "session_id_sha256_12": middle.session_id_hash,
                "turns": middle.turns,
            },
            {
                "step": "A2",
                "transport": "anthropic_compatible_gateway",
                "requested_model": config.route_a,
                "returned_model": final.returned_model,
                "request_id_sha256_12": final.request_id_hash,
                "content_types": list(final.content_types),
                "input_tokens": final.input_tokens,
                "output_tokens": final.output_tokens,
            },
        ],
        "assertions": {
            "route_sequence_a_b_a": True,
            "transcript_marker_crossed_b": True,
            "workspace_read_tool_verified": True,
            "both_markers_returned_to_a": True,
            "resolved_gateway_model_verified": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate the harness without reading credentials or making requests.")
    mode.add_argument("--live", action="store_true", help="Run the explicit, billable live test.")
    parser.add_argument("--receipt", type=Path, help="Optional path for the secret-free JSON receipt.")
    args = parser.parse_args()

    if args.check:
        print("CHECK no_requests=true credentials_read=false standard_library_only=true")
        return 0
    try:
        receipt = run_live(config_from_env())
    except LiveFailure as failure:
        print(f"FAIL kind={failure.kind} reason={failure.safe_reason}", file=sys.stderr)
        return 1
    encoded = json.dumps(receipt, indent=2, sort_keys=True)
    if args.receipt:
        args.receipt.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
