import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import preflight_runtime  # noqa: E402


class RuntimePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_path = ROOT / "templates" / "ai-profiles.example.json"

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
            side_effect=lambda url, timeout: responses[url],
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
            side_effect=lambda url, timeout: responses[url],
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
        }

        with patch.object(
            preflight_runtime,
            "_request_json",
            side_effect=lambda url, timeout: responses[url],
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
            side_effect=lambda url, timeout: responses[url],
        ):
            with self.assertRaises(preflight_runtime.RuntimePreflightError):
                preflight_runtime.preflight(
                    self.profile_path,
                    "development-local",
                )


if __name__ == "__main__":
    unittest.main()
