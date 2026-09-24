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
