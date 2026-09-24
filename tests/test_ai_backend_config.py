import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_ai_config  # noqa: E402


class AIBackendConfigurationTests(unittest.TestCase):
    def test_registry_contains_expected_us_providers(self):
        registry = validate_ai_config.load_registry()
        self.assertEqual(
            {"openai", "anthropic", "google", "meta", "xai"},
            set(registry["providers"]),
        )
        self.assertTrue(
            all(
                provider.get("display_name")
                for provider in registry["providers"].values()
            )
        )

    def test_example_profiles_are_valid(self):
        path = ROOT / "templates" / "ai-profiles.example.json"
        registry = validate_ai_config.load_registry()
        config = validate_ai_config.validate_profile_config(path, registry)
        self.assertEqual("development", config["active_profile"])

    def test_unknown_provider_is_rejected(self):
        config = {
            "schema_version": 2,
            "active_profile": "test",
            "profiles": {
                "test": {
                    "provider": "unknown",
                    "surface": "unknown",
                    "model": None,
                    "connection_mode": "subscription_login",
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai-profiles.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(validate_ai_config.ConfigurationError):
                validate_ai_config.validate_profile_config(path)

    def test_meta_model_api_accepts_only_api_key(self):
        registry = validate_ai_config.load_registry()
        profile = {
            "provider": "meta",
            "surface": "model-api",
            "model": "muse-spark-1.3",
            "connection_mode": "subscription_login",
        }
        with self.assertRaises(validate_ai_config.ConfigurationError):
            validate_ai_config.validate_profile("meta-api", profile, registry)

    def test_muse_code_accepts_subscription_login(self):
        registry = validate_ai_config.load_registry()
        profile = {
            "provider": "meta",
            "surface": "muse-code",
            "model": None,
            "connection_mode": "subscription_login",
        }
        validate_ai_config.validate_profile("meta-agent", profile, registry)

    def test_openai_compatible_profile_requires_model(self):
        registry = validate_ai_config.load_registry()
        profile = {
            "provider": "meta",
            "surface": "model-api",
            "model": None,
            "connection_mode": "api_key",
        }
        with self.assertRaises(validate_ai_config.ConfigurationError):
            validate_ai_config.validate_profile("meta-api", profile, registry)

    def test_renderer_outputs_openhands_llm_settings(self):
        profile_path = ROOT / "templates" / "ai-profiles.example.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "render_openhands_profile.py"),
                str(profile_path),
                "meta-api",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        rendered = json.loads(result.stdout)
        self.assertEqual("llm", rendered["openhands_agent_kind"])
        self.assertEqual("openai/muse-spark-1.3", rendered["llm_model"])
        self.assertEqual("https://api.meta.ai/v1", rendered["llm_base_url"])
        self.assertEqual("MODEL_API_KEY", rendered["api_key_env"])


if __name__ == "__main__":
    unittest.main()
