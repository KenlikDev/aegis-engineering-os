#!/usr/bin/env python3
"""Execute an explicit local OpenHands task through the Agent Server API.

The adapter intentionally targets the verified OpenHands Agent Server contract used by
Aegis. Runtime preflight remains a separate concern and must run before execution.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Literal, Mapping

from evidence_contract import EvidenceContractError, parse_json_object
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


DEFAULT_OPENHANDS_VERSION = "1.49.5"
DEFAULT_TIMEOUT_SECONDS = 3600.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
MAX_JSON_RESPONSE_BYTES = 1024 * 1024
MAX_EVENT_PAGES = 100
MAX_EVENTS = 10_000
DEFAULT_WORKSPACE_ROOT = "/projects"

TERMINAL_STATUSES = frozenset({"finished", "error", "stuck"})
BLOCKED_STATUSES = frozenset({"paused", "waiting_for_confirmation"})
KNOWN_STATUSES = frozenset(
    {
        "idle",
        "running",
        "paused",
        "waiting_for_confirmation",
        "finished",
        "error",
        "stuck",
        "deleting",
    }
)

ExecutionOutcome = Literal["finished", "error", "stuck", "blocked"]
JsonRequest = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, dict[str, Any]],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent a local execution endpoint from redirecting requests elsewhere."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise OpenHandsExecutionError(
            "OpenHands Agent Server returned an unexpected redirect."
        )


_HTTP_OPENER = build_opener(_NoRedirectHandler)


class OpenHandsExecutionError(RuntimeError):
    """Raised when an OpenHands execution cannot be completed safely."""

    def __init__(self, message: str, conversation_id: str | None = None) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id


@dataclass(frozen=True, slots=True)
class OpenHandsExecutionRequest:
    """Explicit inputs for one OpenHands execution attempt."""

    server_url: str
    workspace: str
    task: str
    agent_settings: Mapping[str, Any]
    confirmation_policy: Mapping[str, Any]
    expected_agent_server_version: str = DEFAULT_OPENHANDS_VERSION
    max_iterations: int = 500
    stuck_detection: bool = True
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    workspace_root: str = DEFAULT_WORKSPACE_ROOT
    session_api_key: str | None = None


@dataclass(frozen=True, slots=True)
class OpenHandsExecutionResult:
    """Evidence returned after an execution reaches a stable final state."""

    conversation_id: str
    execution_status: str
    outcome: ExecutionOutcome
    state: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def _request_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    """Issue one JSON request without exposing response bodies in errors."""

    body = None
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=dict(request_headers), method=method)
    try:
        with _HTTP_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_JSON_RESPONSE_BYTES + 1)
            if len(raw) > MAX_JSON_RESPONSE_BYTES:
                raise OpenHandsExecutionError(
                    "OpenHands JSON response exceeds the "
                    f"{MAX_JSON_RESPONSE_BYTES}-byte download limit."
                )
            if not raw:
                return response.status, {}
            parsed = parse_json_object(
                raw,
                label="OpenHands JSON response",
                max_bytes=MAX_JSON_RESPONSE_BYTES,
            )
    except HTTPError as exc:
        # Preserve the HTTP status so callers can intentionally accept a documented
        # non-2xx response such as 409 Conflict from the run endpoint.
        return exc.code, {}
    except (
        URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        EvidenceContractError,
    ) as exc:
        raise OpenHandsExecutionError(
            f"Unable to communicate with OpenHands at {url}: {exc}"
        ) from exc

    return response.status, parsed


def _normalize_server_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("OpenHands server URL must use http or https.")
    if parsed.username or parsed.password:
        raise ValueError("OpenHands server URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("OpenHands server URL must not contain a query or fragment.")
    if not parsed.hostname:
        raise ValueError("OpenHands server URL must contain a hostname.")
    if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Local OpenHands execution requires a loopback server URL.")
    return value.rstrip("/")


def _validate_workspace(workspace: str, workspace_root: str) -> None:
    if not workspace or "\x00" in workspace:
        raise ValueError("OpenHands workspace must be a non-empty path.")
    if not workspace.startswith("/"):
        raise ValueError("OpenHands workspace must be an absolute POSIX path.")
    if any(part == ".." for part in PurePosixPath(workspace).parts):
        raise ValueError(
            "OpenHands workspace must not contain parent traversal components."
        )
    if not workspace_root.startswith("/"):
        raise ValueError("OpenHands workspace root must be an absolute POSIX path.")

    root = PurePosixPath(workspace_root)
    target = PurePosixPath(workspace)
    if target == root:
        raise ValueError(
            "OpenHands workspace must name a project below the workspace root."
        )
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"OpenHands workspace must remain inside the configured root "
            f"{workspace_root!r}."
        ) from exc


def _validate_agent_settings(agent_settings: Mapping[str, Any]) -> None:
    if not isinstance(agent_settings, Mapping):
        raise ValueError("OpenHands agent settings must be an object.")
    if agent_settings.get("agent_kind") != "openhands":
        raise ValueError(
            "The local Ollama execution adapter requires the canonical "
            "OpenHands agent-settings variant."
        )
    if agent_settings.get("tools") is not None:
        raise ValueError(
            "The local Ollama execution adapter must leave tools unset so "
            "OpenHands can materialize its standard execution tool set."
        )

    llm = agent_settings.get("llm")
    if not isinstance(llm, Mapping):
        raise ValueError(
            "OpenHands Agent payload must contain an LLM configuration."
        )
    model = llm.get("model")
    base_url = llm.get("base_url")
    api_key = llm.get("api_key")
    if not isinstance(model, str) or not model.startswith("openai/"):
        raise ValueError(
            "The local Ollama Agent must use an openai/<model> identifier."
        )
    if not isinstance(base_url, str) or not base_url:
        raise ValueError("The OpenHands Agent LLM must declare a base_url.")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError(
            "The OpenHands Agent LLM must declare an API key or local placeholder."
        )


def _validate_request(request: OpenHandsExecutionRequest) -> None:
    _normalize_server_url(request.server_url)
    _validate_workspace(request.workspace, request.workspace_root)
    if not request.task.strip():
        raise ValueError("OpenHands task must not be empty.")
    _validate_agent_settings(request.agent_settings)
    if (
        not isinstance(request.confirmation_policy, Mapping)
        or not request.confirmation_policy.get("kind")
    ):
        raise ValueError(
            "OpenHands confirmation_policy must explicitly select a policy kind."
        )
    if not request.expected_agent_server_version.strip():
        raise ValueError("Expected OpenHands Agent Server version must not be empty.")
    if request.max_iterations <= 0:
        raise ValueError("max_iterations must be greater than zero.")
    if request.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if request.poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than zero.")


def _redact_sensitive_state(value: Any) -> Any:
    """Redact common credential fields from returned execution evidence."""

    sensitive_keys = {
        "api_key",
        "authorization",
        "session_api_key",
        "access_token",
        "refresh_token",
    }
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if key.lower() in sensitive_keys
                else _redact_sensitive_state(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_state(item) for item in value]
    return value


class OpenHandsExecutionClient:
    """Execute one explicitly configured local task through Agent Server."""

    def __init__(self, request_json: JsonRequest | None = None) -> None:
        self._request_json = request_json or self._default_request_json

    @staticmethod
    def _default_request_json(
        method: str,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        return _request_json(method, url, headers, payload)

    def execute(self, request: OpenHandsExecutionRequest) -> OpenHandsExecutionResult:
        """Create, run, and collect one OpenHands conversation."""

        try:
            _validate_request(request)
        except ValueError as exc:
            raise OpenHandsExecutionError(str(exc)) from exc

        base_url = _normalize_server_url(request.server_url)
        headers = {"Accept": "application/json"}
        if request.session_api_key:
            headers["X-Session-API-Key"] = request.session_api_key

        self._verify_server_contract(
            base_url,
            headers,
            request.expected_agent_server_version,
        )

        conversation_id: str | None = None
        try:
            conversation_id = self._create_conversation(base_url, headers, request)
            self._send_message(base_url, headers, conversation_id, request.task)
            self._trigger_run(base_url, headers, conversation_id)
            state, status = self._wait_for_terminal_state(
                base_url,
                headers,
                conversation_id,
                request.timeout_seconds,
                request.poll_interval_seconds,
            )
            events = self._collect_events(base_url, headers, conversation_id)
        except OpenHandsExecutionError as exc:
            if exc.conversation_id is None and conversation_id is not None:
                raise OpenHandsExecutionError(str(exc), conversation_id) from exc
            raise

        if status == "finished":
            outcome: ExecutionOutcome = "finished"
        elif status == "error":
            outcome = "error"
        elif status == "stuck":
            outcome = "stuck"
        else:
            outcome = "blocked"

        return OpenHandsExecutionResult(
            conversation_id=conversation_id,
            execution_status=status,
            outcome=outcome,
            state=_redact_sensitive_state(state),
            events=tuple(_redact_sensitive_state(events)),
        )

    def _verify_server_contract(
        self,
        base_url: str,
        headers: Mapping[str, str],
        expected_version: str,
    ) -> None:
        alive_status, alive = self._request_json(
            "GET", f"{base_url}/alive", headers, None
        )
        if alive_status < 200 or alive_status >= 300 or alive.get("status") != "ok":
            raise OpenHandsExecutionError(
                "OpenHands Agent Server liveness check failed."
            )

        ready_status, ready = self._request_json(
            "GET", f"{base_url}/ready", headers, None
        )
        if (
            ready_status < 200
            or ready_status >= 300
            or ready.get("status") != "ready"
        ):
            raise OpenHandsExecutionError(
                "OpenHands Agent Server readiness check failed."
            )

        info_status, info = self._request_json(
            "GET", f"{base_url}/server_info", headers, None
        )
        if info_status < 200 or info_status >= 300:
            raise OpenHandsExecutionError(
                "OpenHands Agent Server information check failed."
            )

        if info.get("version") != expected_version:
            raise OpenHandsExecutionError(
                "OpenHands Agent Server version does not match the expected contract."
            )
        if info.get("conversation_runtime") != "local":
            raise OpenHandsExecutionError(
                "OpenHands Agent Server must report conversation_runtime=local."
            )
        for field in (
            "version",
            "sdk_version",
            "tools_version",
            "workspace_version",
        ):
            if not isinstance(info.get(field), str) or not info[field]:
                raise OpenHandsExecutionError(
                    f"OpenHands Agent Server /server_info is missing {field}."
                )

    def _create_conversation(
        self,
        base_url: str,
        headers: Mapping[str, str],
        request: OpenHandsExecutionRequest,
    ) -> str:
        payload = {
            "agent_settings": dict(request.agent_settings),
            "initial_message": None,
            "max_iterations": request.max_iterations,
            "stuck_detection": request.stuck_detection,
            "workspace": {"working_dir": request.workspace},
            "confirmation_policy": dict(request.confirmation_policy),
        }
        status, data = self._request_json(
            "POST",
            f"{base_url}/api/conversations",
            headers,
            payload,
        )
        if status < 200 or status >= 300:
            raise OpenHandsExecutionError("OpenHands conversation creation failed.")

        raw_id = data.get("id") or data.get("conversation_id")
        if not isinstance(raw_id, str) or not raw_id:
            raise OpenHandsExecutionError(
                "OpenHands conversation creation returned no conversation id."
            )
        try:
            return str(uuid.UUID(raw_id))
        except ValueError as exc:
            raise OpenHandsExecutionError(
                "OpenHands returned an invalid conversation id."
            ) from exc

    def _send_message(
        self,
        base_url: str,
        headers: Mapping[str, str],
        conversation_id: str,
        task: str,
    ) -> None:
        payload = {
            "role": "user",
            "content": [{"type": "text", "text": task}],
            "run": False,
        }
        status, _ = self._request_json(
            "POST",
            f"{base_url}/api/conversations/{conversation_id}/events",
            headers,
            payload,
        )
        if status < 200 or status >= 300:
            raise OpenHandsExecutionError(
                "OpenHands user message submission failed.",
                conversation_id,
            )

    def _trigger_run(
        self,
        base_url: str,
        headers: Mapping[str, str],
        conversation_id: str,
    ) -> None:
        status, _ = self._request_json(
            "POST",
            f"{base_url}/api/conversations/{conversation_id}/run",
            headers,
            None,
        )
        if status not in {200, 201, 204, 409}:
            raise OpenHandsExecutionError(
                "OpenHands run trigger failed.",
                conversation_id,
            )

    def _get_state(
        self,
        base_url: str,
        headers: Mapping[str, str],
        conversation_id: str,
    ) -> dict[str, Any]:
        status, state = self._request_json(
            "GET",
            f"{base_url}/api/conversations/{conversation_id}",
            headers,
            None,
        )
        if status < 200 or status >= 300:
            raise OpenHandsExecutionError(
                "Unable to read OpenHands conversation state.",
                conversation_id,
            )
        return state

    def _wait_for_terminal_state(
        self,
        base_url: str,
        headers: Mapping[str, str],
        conversation_id: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> tuple[dict[str, Any], str]:
        deadline = time.monotonic() + timeout_seconds
        candidate: str | None = None

        while True:
            state = self._get_state(base_url, headers, conversation_id)
            status = state.get("execution_status")
            if not isinstance(status, str) or status not in KNOWN_STATUSES:
                raise OpenHandsExecutionError(
                    "OpenHands conversation returned an unknown execution status.",
                    conversation_id,
                )

            if status in BLOCKED_STATUSES:
                return state, status
            if status == "deleting":
                raise OpenHandsExecutionError(
                    "OpenHands conversation entered deleting state during execution.",
                    conversation_id,
                )
            if status in TERMINAL_STATUSES:
                # Require two consecutive matching terminal observations. This reduces
                # the risk of accepting a transient FINISHED status before a stop hook
                # moves the server back to RUNNING.
                if candidate == status:
                    return state, status
                candidate = status
            else:
                candidate = None

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OpenHandsExecutionError(
                    "Timed out while waiting for OpenHands execution to finish.",
                    conversation_id,
                )
            time.sleep(min(poll_interval_seconds, remaining))

    def _collect_events(
        self,
        base_url: str,
        headers: Mapping[str, str],
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        page_id: str | None = None
        seen_pages: set[str] = set()
        page_count = 0

        while True:
            if page_count >= MAX_EVENT_PAGES:
                raise OpenHandsExecutionError(
                    "OpenHands event pagination exceeded the "
                    f"{MAX_EVENT_PAGES}-page limit.",
                    conversation_id,
                )
            page_count += 1
            query = {"limit": "100"}
            if page_id:
                query["page_id"] = page_id
            url = (
                f"{base_url}/api/conversations/{conversation_id}/events/search?"
                f"{urlencode(query)}"
            )
            status, data = self._request_json("GET", url, headers, None)
            if status < 200 or status >= 300:
                raise OpenHandsExecutionError(
                    "Unable to retrieve OpenHands execution events.",
                    conversation_id,
                )

            items = data.get("items")
            if not isinstance(items, list) or any(
                not isinstance(item, dict) for item in items
            ):
                raise OpenHandsExecutionError(
                    "OpenHands event search returned an invalid items list.",
                    conversation_id,
                )
            if len(events) + len(items) > MAX_EVENTS:
                raise OpenHandsExecutionError(
                    "OpenHands execution event history exceeded the "
                    f"{MAX_EVENTS}-event limit.",
                    conversation_id,
                )
            events.extend(items)

            next_page_id = data.get("next_page_id")
            if not next_page_id:
                return events
            if not isinstance(next_page_id, str) or next_page_id in seen_pages:
                raise OpenHandsExecutionError(
                    "OpenHands event pagination returned a cyclic page id.",
                    conversation_id,
                )
            seen_pages.add(next_page_id)
            page_id = next_page_id
