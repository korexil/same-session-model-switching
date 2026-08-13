"""Standard-library client for a shell/gateway-specific switching bridge."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from switch_controller import (
    FailureKind,
    ModelEntry,
    ProbeResult,
    RouteEvidence,
    Ticket,
    TypedFailure,
)


class HttpBridge:
    """Calls a local or HTTPS bridge without owning provider credentials."""

    def __init__(
        self,
        base_url: str,
        *,
        token: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = urlparse(base_url)
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("bridge URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("bridge URL must not contain credentials, query, or fragment")
        if parsed.scheme != "https" and parsed.hostname not in local_hosts:
            raise ValueError("remote bridge URL must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def probe(self, ticket: Ticket) -> ProbeResult:
        return self._evidence_call("/v1/probe", ticket, ticket.target, "probe")

    def observe(
        self,
        ticket: Ticket,
        *,
        route: Optional[ModelEntry] = None,
        phase: str = "forward",
    ) -> ProbeResult:
        expected = route or ticket.target
        return self._evidence_call("/v1/evidence", ticket, expected, phase)

    def dispatch(
        self,
        ticket: Ticket,
        *,
        route: Optional[ModelEntry] = None,
        phase: str = "forward",
    ) -> Optional[TypedFailure]:
        expected = route or ticket.target
        response = self._post(
            "/v1/switch", self._ticket_payload(ticket, expected, phase)
        )
        if isinstance(response, TypedFailure):
            return response
        if response.get("accepted") is True:
            return None
        return TypedFailure(FailureKind.PROTOCOL_VIOLATION, "switch_not_accepted")

    def _evidence_call(
        self, path: str, ticket: Ticket, route: ModelEntry, phase: str
    ) -> ProbeResult:
        response = self._post(path, self._ticket_payload(ticket, route, phase))
        if isinstance(response, TypedFailure):
            return response
        evidence = response.get("evidence")
        if not isinstance(evidence, Mapping):
            return TypedFailure(FailureKind.PROTOCOL_VIOLATION, "evidence_missing")
        try:
            text_fields = {
                name: evidence[name]
                for name in (
                    "alias",
                    "provider",
                    "upstream_model",
                    "transport",
                    "session_id",
                    "request_id",
                    "correlation_id",
                )
            }
            if not all(isinstance(value, str) and value for value in text_fields.values()):
                raise ValueError("invalid text field")
            revision = evidence["switch_revision"]
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise ValueError("invalid revision")
            observed_at = float(evidence["observed_at"])
            expires_at = float(evidence["expires_at"])
            if not all(map(math.isfinite, (observed_at, expires_at))):
                raise ValueError("invalid timestamp")
            return RouteEvidence(
                alias=text_fields["alias"],
                provider=text_fields["provider"],
                upstream_model=text_fields["upstream_model"],
                transport=text_fields["transport"],
                session_id=text_fields["session_id"],
                request_id=text_fields["request_id"],
                switch_revision=revision,
                correlation_id=text_fields["correlation_id"],
                observed_at=observed_at,
                expires_at=expires_at,
            )
        except (KeyError, TypeError, ValueError):
            return TypedFailure(FailureKind.PROTOCOL_VIOLATION, "invalid_evidence")

    def _post(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any] | TypedFailure:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except HTTPError as error:
            retry_after = _retry_after(
                None if error.headers is None else error.headers.get("Retry-After")
            )
            return TypedFailure(
                _http_failure_kind(error.code),
                f"bridge_http_{error.code}",
                retry_after,
            )
        except (URLError, TimeoutError, OSError):
            return TypedFailure(FailureKind.TRANSPORT_FAILURE, "bridge_unreachable")

        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return TypedFailure(FailureKind.PROTOCOL_VIOLATION, "invalid_json")
        if not isinstance(decoded, Mapping):
            return TypedFailure(FailureKind.PROTOCOL_VIOLATION, "invalid_response_shape")
        failure = decoded.get("failure")
        if failure is not None:
            return _parse_failure(failure)
        return decoded

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    @staticmethod
    def _ticket_payload(
        ticket: Ticket, route_entry: ModelEntry, phase: str
    ) -> dict[str, Any]:
        if phase not in {"probe", "forward", "rollback"}:
            raise ValueError("invalid bridge phase")
        route = asdict(route_entry)
        route["capabilities"] = sorted(route_entry.capabilities)
        return {
            "session_id": ticket.session_id,
            "switch_revision": ticket.revision,
            "correlation_id": ticket.correlation_id,
            "requested_at": ticket.requested_at,
            "phase": phase,
            "route": route,
        }


def _parse_failure(value: object) -> TypedFailure:
    if not isinstance(value, Mapping):
        return TypedFailure(FailureKind.PROTOCOL_VIOLATION, "invalid_failure")
    try:
        raw_kind = value["kind"]
        reason = value["safe_reason"]
        if not isinstance(raw_kind, str) or not isinstance(reason, str) or not reason:
            raise ValueError("invalid failure fields")
        kind = FailureKind(raw_kind)
        retry = value.get("retry_after_seconds")
        retry_seconds = None if retry is None else float(retry)
        if retry_seconds is not None and (
            not math.isfinite(retry_seconds) or retry_seconds < 0
        ):
            raise ValueError("invalid retry interval")
        return TypedFailure(kind, reason, retry_seconds)
    except (KeyError, TypeError, ValueError):
        return TypedFailure(FailureKind.PROTOCOL_VIOLATION, "invalid_failure")


def _http_failure_kind(status: int) -> FailureKind:
    if status in {401, 403}:
        return FailureKind.AUTH_REJECTED
    if status == 429:
        return FailureKind.RATE_LIMITED
    if status >= 500:
        return FailureKind.PROVIDER_FAILURE
    return FailureKind.PROTOCOL_VIOLATION


def _retry_after(value: Optional[str]) -> Optional[float]:
    try:
        return None if value is None else max(0.0, float(value))
    except ValueError:
        return None
