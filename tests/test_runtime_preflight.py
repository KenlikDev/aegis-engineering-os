import sys
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import preflight_runtime  # noqa: E402
from evidence_contract import read_and_validate_evidence  # noqa: E402


class RuntimePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_path = ROOT / "templates" / "ai-profiles.example.json"

    def test_request_json_rejects_redirects(self) -> None:
        handler = preflight_runtime._NoRedirectHandler()
        with self.assertRaisesRegex(
            preflight_runtime.RuntimePreflightError,
            "unexpected redirect",
        ):
            handler.redirect_request(Request("http://127.0.0.1:9000/api/settings"))

    def test_request_json_rejects_duplicate_keys(self) -> None:
        from preflight_runtime import _request_json

        class DuplicateResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, limit):
                return b'{"status":"ok","status":"verified"}'

        class DuplicateOpener:
            def open(self, request, timeout):  # noqa: ANN001, ARG002
                return DuplicateResponse()

        with patch("preflight_runtime._NO_REDIRECT_OPENER", DuplicateOpener()):
            with self.assertRaisesRegex(
                preflight_runtime.RuntimePreflightError,
                "Duplicate JSON key",
            ):
                _request_json("http://127.0.0.1:11434/api/version", 5)

    def test_request_json_rejects_oversized_response(self) -> None:
        from preflight_runtime import MAX_JSON_RESPONSE_BYTES, _request_json

        class OversizedResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, limit):
                return b"{" + b"x" * limit

        class OversizedOpener:
            def open(self, request, timeout):  # noqa: ANN001, ARG002
                return OversizedResponse()

        with patch("preflight_runtime._NO_REDIRECT_OPENER", OversizedOpener()):
            with self.assertRaisesRegex(
                preflight_runtime.RuntimePreflightError,
                f"{MAX_JSON_RESPONSE_BYTES}-byte download limit",
            ):
                _request_json("http://127.0.0.1:11434/api/version", 5)

    def test_preflight_verifies_exact_local_model(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [
                    {"name": "llama3.2:latest"},
                    {"name": "gemma4:31b"},
                ]
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            result = preflight_runtime.preflight(
                self.profile_path,
                "development-local",
            )

        self.assertEqual("verified", result["status"])
        self.assertEqual("ollama", result["provider"])
        self.assertEqual("gemma4:31b", result["model"])
        self.assertEqual("0.12.0", result["ollama_version"])
        self.assertTrue(result["model_available"])

    def test_cli_writes_canonical_runtime_preflight_evidence(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
        }

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "runtime-preflight.json"
            argv = [
                "preflight_runtime.py",
                str(self.profile_path),
                "development-local",
                "--canonical-evidence-output",
                str(output),
            ]
            with (
                patch.object(
                    preflight_runtime,
                    "_request_json",
                    side_effect=lambda url, timeout, headers=None: responses[url],
                ),
                patch.object(sys, "argv", argv),
            ):
                self.assertEqual(0, preflight_runtime.main())

            canonical = read_and_validate_evidence(output)
            self.assertEqual("runtime-preflight", canonical.kind)
            self.assertEqual("profile:development-local", canonical.subject)
            self.assertEqual("gemma4:31b", canonical.result["model"])

    def test_cli_refuses_to_overwrite_profile_with_canonical_evidence(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
        }

        argv = [
            "preflight_runtime.py",
            str(self.profile_path),
            "development-local",
            "--canonical-evidence-output",
            str(self.profile_path),
        ]
        with (
            patch.object(
                preflight_runtime,
                "_request_json",
                side_effect=lambda url, timeout, headers=None: responses[url],
            ),
            patch.object(sys, "argv", argv),
        ):
            self.assertEqual(1, preflight_runtime.main())

    def test_preflight_rejects_missing_exact_model(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:latest"}]
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            with self.assertRaises(preflight_runtime.RuntimePreflightError):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                )

    def test_preflight_rejects_non_local_profile(self) -> None:
        with self.assertRaises(preflight_runtime.RuntimePreflightError):
            preflight_runtime.preflight(
                self.profile_path,
                "development",
            )

    def test_preflight_verifies_openhands_agent_server(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
            "http://127.0.0.1:9000/alive": {"status": "ok"},
            "http://127.0.0.1:9000/ready": {"status": "ready"},
            "http://127.0.0.1:9000/server_info": {
                "version": "0.12.1",
                "sdk_version": "1.2.3",
                "tools_version": "1.2.4",
                "workspace_version": "1.2.5",
                "build_git_sha": "abc123",
                "build_git_ref": "main",
                "conversation_runtime": "local",
            },
            "http://127.0.0.1:9000/api/settings": {
                "agent_settings": {
                    "agent_kind": "openhands",
                    "llm": {
                        "model": "openai/gemma4:31b",
                        "base_url": "http://host.docker.internal:11434/v1",
                    },
                },
                "llm_api_key_is_set": True,
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            result = preflight_runtime.preflight(
                self.profile_path,
                "development-local",
                openhands_agent_server_url="http://127.0.0.1:9000/",
            )

        self.assertEqual("verified", result["openhands_agent_server"]["status"])
        self.assertEqual(
            "http://127.0.0.1:9000",
            result["openhands_agent_server"]["base_url"],
        )
        self.assertEqual(
            "0.12.1",
            result["openhands_agent_server"]["version"],
        )
        self.assertEqual(
            "1.2.3",
            result["openhands_agent_server"]["sdk_version"],
        )
        self.assertEqual(
            "abc123",
            result["openhands_agent_server"]["build_git_sha"],
        )
        self.assertEqual(
            "openai/gemma4:31b",
            result["openhands_agent_server"]["active_llm_model"],
        )
        self.assertEqual(
            "http://host.docker.internal:11434/v1",
            result["openhands_agent_server"]["llm_base_url"],
        )
        self.assertTrue(result["openhands_agent_server"]["llm_api_key_is_set"])

    def test_preflight_rejects_mismatched_active_llm_base_url(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
            "http://127.0.0.1:9000/alive": {"status": "ok"},
            "http://127.0.0.1:9000/ready": {"status": "ready"},
            "http://127.0.0.1:9000/server_info": {
                "version": "0.12.1",
                "sdk_version": "1.2.3",
                "tools_version": "1.2.4",
                "workspace_version": "1.2.5",
                "conversation_runtime": "local",
            },
            "http://127.0.0.1:9000/api/settings": {
                "agent_settings": {
                    "agent_kind": "openhands",
                    "llm": {
                        "model": "openai/gemma4:31b",
                        "base_url": "http://127.0.0.1:11434/v1",
                    },
                },
                "llm_api_key_is_set": True,
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            with self.assertRaises(preflight_runtime.RuntimePreflightError):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                    openhands_agent_server_url="http://127.0.0.1:9000",
                )

    def test_preflight_rejects_mismatched_active_model(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
            "http://127.0.0.1:9000/alive": {"status": "ok"},
            "http://127.0.0.1:9000/ready": {"status": "ready"},
            "http://127.0.0.1:9000/server_info": {
                "version": "0.12.1",
                "sdk_version": "1.2.3",
                "tools_version": "1.2.4",
                "workspace_version": "1.2.5",
                "conversation_runtime": "local",
            },
            "http://127.0.0.1:9000/api/settings": {
                "agent_settings": {
                    "agent_kind": "openhands",
                    "llm": {
                        "model": "openai/other-model",
                        "base_url": "http://host.docker.internal:11434/v1",
                    },
                },
                "llm_api_key_is_set": True,
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            with self.assertRaises(preflight_runtime.RuntimePreflightError):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                    openhands_agent_server_url="http://127.0.0.1:9000",
                )

    def test_preflight_rejects_non_loopback_agent_server_url(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            with self.assertRaisesRegex(
                preflight_runtime.RuntimePreflightError,
                "loopback server URL",
            ):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                    openhands_agent_server_url="https://example.invalid:9000",
                )

    def test_preflight_rejects_agent_server_url_credentials_and_query(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            for url in (
                "http://user:password@127.0.0.1:9000",
                "http://127.0.0.1:9000?token=secret",
                "http://127.0.0.1:9000/#fragment",
            ):
                with self.subTest(url=url):
                    with self.assertRaises(preflight_runtime.RuntimePreflightError):
                        preflight_runtime.preflight(
                            self.profile_path,
                            "development-local",
                            openhands_agent_server_url=url,
                        )

    def test_preflight_rejects_non_local_openhands_agent_server(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
            "http://127.0.0.1:9000/alive": {"status": "ok"},
            "http://127.0.0.1:9000/ready": {"status": "ready"},
            "http://127.0.0.1:9000/server_info": {
                "version": "0.12.1",
                "sdk_version": "1.2.3",
                "tools_version": "1.2.4",
                "workspace_version": "1.2.5",
                "conversation_runtime": "remote",
            },
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            with self.assertRaises(preflight_runtime.RuntimePreflightError):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                    openhands_agent_server_url="http://127.0.0.1:9000",
                )

    def test_preflight_sends_optional_session_api_key(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
            "http://127.0.0.1:9000/alive": {"status": "ok"},
            "http://127.0.0.1:9000/ready": {"status": "ready"},
            "http://127.0.0.1:9000/server_info": {
                "version": "0.12.1",
                "sdk_version": "1.2.3",
                "tools_version": "1.2.4",
                "workspace_version": "1.2.5",
                "conversation_runtime": "local",
            },
            "http://127.0.0.1:9000/api/settings": {
                "agent_settings": {
                    "agent_kind": "openhands",
                    "llm": {
                        "model": "openai/gemma4:31b",
                        "base_url": "http://host.docker.internal:11434/v1",
                    },
                },
                "llm_api_key_is_set": True,
            },
        }
        captured_headers = []

        def request_json(url: str, timeout: int, headers=None) -> dict:
            if url.endswith("/api/settings"):
                captured_headers.append(headers)
            return responses[url]

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=request_json,
        ):
            preflight_runtime.preflight(
                self.profile_path,
                "development-local",
                openhands_agent_server_url="http://127.0.0.1:9000",
                openhands_agent_server_api_key="test-session-key",
            )

        self.assertEqual(
            [{"X-Session-API-Key": "test-session-key"}],
            captured_headers,
        )

    def test_preflight_rejects_unready_openhands_agent_server(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {
                "models": [{"name": "gemma4:31b"}]
            },
            "http://127.0.0.1:9000/alive": {"status": "ok"},
        }

        def request_json(url: str, timeout: int) -> dict:
            if url.endswith("/ready"):
                raise preflight_runtime.RuntimePreflightError(
                    "OpenHands Agent Server is reachable but not ready."
                )
            return responses[url]

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=request_json,
        ):
            with self.assertRaises(preflight_runtime.RuntimePreflightError):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                    openhands_agent_server_url="http://127.0.0.1:9000",
                )

    def test_preflight_rejects_invalid_ollama_payload(self) -> None:
        responses = {
            "http://127.0.0.1:11434/api/version": {"version": "0.12.0"},
            "http://127.0.0.1:11434/api/tags": {"models": "invalid"},
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout, headers=None: responses[url],
        ):
            with self.assertRaises(preflight_runtime.RuntimePreflightError):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                )


if __name__ == "__main__":
    unittest.main()
