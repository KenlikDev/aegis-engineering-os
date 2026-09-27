import sys
import unittest
import uuid
from dataclasses import replace
from urllib.error import HTTPError
from unittest.mock import patch
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from openhands_execution import (  # noqa: E402
    OpenHandsExecutionClient,
    OpenHandsExecutionError,
    OpenHandsExecutionRequest,
)


SERVER = "http://127.0.0.1:8000"
CID = "12345678-1234-5678-1234-567812345678"


def request_data() -> OpenHandsExecutionRequest:
    return OpenHandsExecutionRequest(
        server_url=SERVER,
        workspace="/projects/demo",
        task="Implement the requested change.",
        agent={
            "kind": "Agent",
            "llm": {
                "model": "openai/gemma4:31b",
                "base_url": "http://host.docker.internal:11434/v1",
                "api_key": "local-llm",
            },
        },
        confirmation_policy={
            "kind": "ConfirmRisky",
            "threshold": "HIGH",
            "confirm_unknown": True,
        },
        timeout_seconds=1.0,
        poll_interval_seconds=0.001,
    )


class FakeTransport:
    def __init__(
        self,
        responses: Mapping[
            tuple[str, str], list[tuple[int, dict[str, Any]]]
        ],
    ) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls: list[
            tuple[str, str, dict[str, Any] | None, dict[str, str]]
        ] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append(
            (
                method,
                url,
                dict(payload) if payload is not None else None,
                dict(headers),
            )
        )
        key = (method, url.split("?")[0])
        responses = self.responses.get(key)
        if not responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return responses.pop(0)


BASE_RESPONSES = {
    ("GET", f"{SERVER}/alive"): [(200, {"status": "ok"})],
    ("GET", f"{SERVER}/ready"): [(200, {"status": "ready"})],
    ("GET", f"{SERVER}/server_info"): [
        (
            200,
            {
                "version": "1.49.5",
                "sdk_version": "1.49.5",
                "tools_version": "1.49.5",
                "workspace_version": "1.49.5",
                "conversation_runtime": "local",
            },
        )
    ],
    ("POST", f"{SERVER}/api/conversations"): [(201, {"id": CID})],
    ("POST", f"{SERVER}/api/conversations/{CID}/events"): [(200, {})],
    ("POST", f"{SERVER}/api/conversations/{CID}/run"): [(204, {})],
}


def responses_with_states(
    statuses: list[str],
) -> dict[tuple[str, str], list[tuple[int, dict[str, Any]]]]:
    data = {key: list(value) for key, value in BASE_RESPONSES.items()}
    data[("GET", f"{SERVER}/api/conversations/{CID}")] = [
        (200, {"id": CID, "execution_status": status}) for status in statuses
    ]
    data[("GET", f"{SERVER}/api/conversations/{CID}/events/search")] = [
        (
            200,
            {
                "items": [{"id": "event-1", "type": "MessageEvent"}],
                "next_page_id": None,
            },
        )
    ]
    return data


class OpenHandsExecutionTests(unittest.TestCase):
    def test_execution_orders_create_message_run_state_and_events(self) -> None:
        transport = FakeTransport(
            responses_with_states(["running", "finished", "finished"])
        )
        result = OpenHandsExecutionClient(transport).execute(request_data())

        self.assertEqual("finished", result.outcome)
        urls = [(method, url.split("?")[0]) for method, url, _, _ in transport.calls]
        self.assertEqual(
            [
                ("GET", f"{SERVER}/alive"),
                ("GET", f"{SERVER}/ready"),
                ("GET", f"{SERVER}/server_info"),
                ("POST", f"{SERVER}/api/conversations"),
                ("POST", f"{SERVER}/api/conversations/{CID}/events"),
                ("POST", f"{SERVER}/api/conversations/{CID}/run"),
                ("GET", f"{SERVER}/api/conversations/{CID}"),
                ("GET", f"{SERVER}/api/conversations/{CID}"),
                ("GET", f"{SERVER}/api/conversations/{CID}"),
                ("GET", f"{SERVER}/api/conversations/{CID}/events/search"),
            ],
            urls,
        )
        create_payload = transport.calls[3][2]
        self.assertEqual(
            {"working_dir": "/projects/demo"},
            create_payload["workspace"],
        )
        self.assertEqual(
            "ConfirmRisky",
            create_payload["confirmation_policy"]["kind"],
        )
        self.assertFalse(transport.calls[4][2]["run"])

    def test_session_api_key_is_sent_but_never_exposed_by_result(self) -> None:
        request = replace(request_data(), session_api_key="secret-value")
        transport = FakeTransport(responses_with_states(["finished", "finished"]))
        result = OpenHandsExecutionClient(transport).execute(request)

        self.assertEqual(
            "secret-value",
            transport.calls[2][3]["X-Session-API-Key"],
        )
        self.assertNotIn("secret-value", repr(result))

    def test_agent_api_key_is_redacted_from_returned_state(self) -> None:
        request = replace(
            request_data(),
            agent={
                **request_data().agent,
                "llm": {
                    **request_data().agent["llm"],
                    "api_key": "llm-secret-value",
                },
            },
        )
        responses = responses_with_states(["finished", "finished"])
        responses[("GET", f"{SERVER}/api/conversations/{CID}")] = [
            (
                200,
                {
                    "id": CID,
                    "execution_status": "finished",
                    "agent": {
                        "kind": "Agent",
                        "llm": {
                            "model": "openai/gemma4:31b",
                            "api_key": "llm-secret-value",
                        },
                    },
                },
            ),
            (
                200,
                {
                    "id": CID,
                    "execution_status": "finished",
                    "agent": {
                        "kind": "Agent",
                        "llm": {
                            "model": "openai/gemma4:31b",
                            "api_key": "llm-secret-value",
                        },
                    },
                },
            ),
        ]
        responses[("GET", f"{SERVER}/api/conversations/{CID}/events/search")] = [
            (
                200,
                {
                    "items": [
                        {
                            "id": "event-1",
                            "type": "MessageEvent",
                            "api_key": "event-secret",
                        }
                    ],
                    "next_page_id": None,
                },
            )
        ]
        transport = FakeTransport(responses)
        result = OpenHandsExecutionClient(transport).execute(request)

        self.assertEqual("[REDACTED]", result.state["agent"]["llm"]["api_key"])
        self.assertEqual("[REDACTED]", result.events[0]["api_key"])
        self.assertNotIn("llm-secret-value", repr(result))
        self.assertNotIn("event-secret", repr(result))

    def test_real_http_409_is_returned_for_status_specific_handling(self) -> None:
        response = HTTPError(
            f"{SERVER}/api/conversations/{CID}/run",
            409,
            "Conflict",
            {},
            None,
        )

        class ErrorOpener:
            def open(self, request, timeout):  # noqa: ANN001, ARG002
                raise response

        with patch("openhands_execution._HTTP_OPENER", ErrorOpener()):
            from openhands_execution import _request_json

            status, payload = _request_json(
                "POST",
                f"{SERVER}/api/conversations/{CID}/run",
                {},
                None,
            )

        self.assertEqual(409, status)
        self.assertEqual({}, payload)

    def test_waiting_for_confirmation_is_a_blocked_outcome(self) -> None:
        transport = FakeTransport(
            responses_with_states(["waiting_for_confirmation"])
        )
        result = OpenHandsExecutionClient(transport).execute(request_data())
        self.assertEqual("blocked", result.outcome)
        self.assertEqual("waiting_for_confirmation", result.execution_status)

    def test_paused_is_a_blocked_outcome(self) -> None:
        transport = FakeTransport(responses_with_states(["paused"]))
        result = OpenHandsExecutionClient(transport).execute(request_data())
        self.assertEqual("blocked", result.outcome)
        self.assertEqual("paused", result.execution_status)

    def test_error_and_stuck_are_terminal_outcomes(self) -> None:
        for status in ("error", "stuck"):
            with self.subTest(status=status):
                transport = FakeTransport(
                    responses_with_states([status, status])
                )
                result = OpenHandsExecutionClient(transport).execute(
                    request_data()
                )
                self.assertEqual(status, result.outcome)

    def test_version_mismatch_stops_before_mutation(self) -> None:
        responses = responses_with_states(["finished", "finished"])
        responses[("GET", f"{SERVER}/server_info")] = [
            (
                200,
                {
                    "version": "1.49.6",
                    "sdk_version": "1.49.6",
                    "tools_version": "1.49.6",
                    "workspace_version": "1.49.6",
                    "conversation_runtime": "local",
                },
            )
        ]
        transport = FakeTransport(responses)
        with self.assertRaises(OpenHandsExecutionError):
            OpenHandsExecutionClient(transport).execute(request_data())
        self.assertFalse(any(call[0] == "POST" for call in transport.calls))

    def test_workspace_escape_is_rejected(self) -> None:
        request = replace(
            request_data(),
            workspace="/projects/../outside",
        )
        with self.assertRaises(OpenHandsExecutionError):
            OpenHandsExecutionClient(lambda *args: (200, {})).execute(request)

    def test_non_loopback_server_is_rejected(self) -> None:
        request = replace(
            request_data(),
            server_url="http://192.0.2.10:8000",
        )
        with self.assertRaises(OpenHandsExecutionError):
            OpenHandsExecutionClient(lambda *args: (200, {})).execute(request)

    def test_timeout_preserves_conversation_id(self) -> None:
        responses = responses_with_states(["running"] + ["running"] * 20)
        request = replace(
            request_data(),
            timeout_seconds=0.01,
            poll_interval_seconds=0.001,
        )
        transport = FakeTransport(responses)
        with self.assertRaises(OpenHandsExecutionError) as context:
            OpenHandsExecutionClient(transport).execute(request)
        self.assertEqual(CID, context.exception.conversation_id)

    def test_malformed_event_pagination_is_rejected(self) -> None:
        responses = responses_with_states(["finished", "finished"])
        responses[("GET", f"{SERVER}/api/conversations/{CID}/events/search")] = [
            (200, {"items": [], "next_page_id": "loop"}),
            (200, {"items": [], "next_page_id": "loop"}),
        ]
        transport = FakeTransport(responses)
        with self.assertRaises(OpenHandsExecutionError):
            OpenHandsExecutionClient(transport).execute(request_data())

    def test_http_409_run_trigger_is_accepted(self) -> None:
        responses = responses_with_states(["running", "finished", "finished"])
        responses[("POST", f"{SERVER}/api/conversations/{CID}/run")] = [(409, {})]
        transport = FakeTransport(responses)
        result = OpenHandsExecutionClient(transport).execute(request_data())
        self.assertEqual("finished", result.outcome)


if __name__ == "__main__":
    unittest.main()
