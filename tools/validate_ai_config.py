#!/usr/bin/env python3
"""Validate the provider-neutral Aegis AI backend registry and user profiles."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "ai-backends.json"
PROFILE_SCHEMA_VERSION = 2
PROVIDER_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SURFACE_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROFILE_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_CONNECTION_MODES = {"subscription_login", "api_key", "local"}
ALLOWED_INTEGRATIONS = {
    "openhands_acp",
    "openhands_llm_openai_compatible",
    "openhands_llm_ollama",
    "custom_agent",
}


class ConfigurationError(ValueError):
    """Raised when an Aegis AI configuration is invalid."""


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Unable to read {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise ConfigurationError(f"{path} must contain a JSON object.")
    return value


def load_registry() -> dict:
    registry = load_json(REGISTRY_PATH)

    if registry.get("schema_version") != 2:
        raise ConfigurationError("Unsupported AI backend registry schema version.")

    policy = registry.get("policy")
    providers = registry.get("providers")
    if not isinstance(policy, dict) or not isinstance(providers, dict) or not providers:
        raise ConfigurationError("AI backend registry must contain policy and providers.")

    allowed_origins = policy.get("allowed_provider_origins")
    if allowed_origins != ["US", "LOCAL"]:
        raise ConfigurationError("AI backend registry must explicitly allow US and LOCAL provider origins.")
    if policy.get("selection") != "user-controlled":
        raise ConfigurationError("AI backend selection must remain user-controlled.")
    if policy.get("secret_storage") != "environment-or-provider-login":
        raise ConfigurationError("AI secrets must remain outside repository configuration.")
    if policy.get("automatic_model_selection") is not False:
        raise ConfigurationError("Aegis must not automatically select a model.")

    for provider_name, provider in providers.items():
        if not PROVIDER_NAME_PATTERN.fullmatch(provider_name):
            raise ConfigurationError(f"Invalid provider name: {provider_name!r}.")
        if not isinstance(provider, dict):
            raise ConfigurationError(f"Provider {provider_name!r} must be an object.")

        origin = provider.get("origin")
        if origin not in allowed_origins:
            raise ConfigurationError(f"Provider {provider_name!r} has unsupported origin: {origin!r}.")

        surfaces = provider.get("surfaces")
        if not isinstance(surfaces, dict) or not surfaces:
            raise ConfigurationError(
                f"Provider {provider_name!r} must declare surfaces."
            )

        for surface_name, surface in surfaces.items():
            if not SURFACE_NAME_PATTERN.fullmatch(surface_name):
                raise ConfigurationError(f"Invalid surface name: {surface_name!r}.")
            if not isinstance(surface, dict):
                raise ConfigurationError(
                    f"Surface {provider_name}/{surface_name} must be an object."
                )

            integration = surface.get("integration")
            modes = surface.get("connection_modes")
            if integration not in ALLOWED_INTEGRATIONS:
                raise ConfigurationError(
                    f"Unsupported integration for {provider_name}/{surface_name}: "
                    f"{integration!r}."
                )
            if (
                not isinstance(modes, list)
                or not modes
                or not set(modes) <= ALLOWED_CONNECTION_MODES
            ):
                raise ConfigurationError(
                    f"Invalid connection modes for {provider_name}/{surface_name}."
                )

            if "local" in modes and origin != "LOCAL":
                raise ConfigurationError(f"{provider_name}/{surface_name} uses local mode but provider origin is not LOCAL.")
            if origin == "LOCAL" and "local" not in modes:
                raise ConfigurationError(f"{provider_name}/{surface_name} must declare local connection mode.")

            if integration == "openhands_llm_ollama":
                ollama_base_url = surface.get("ollama_base_url")
                if "local" not in modes or not isinstance(ollama_base_url, str) or not ollama_base_url.startswith(("http://", "https://")):
                    raise ConfigurationError(f"{provider_name}/{surface_name} requires local mode and a valid ollama_base_url.")

            if integration == "openhands_llm_openai_compatible":
                base_url = surface.get("base_url")
                model_prefix = surface.get("model_prefix")
                if not isinstance(base_url, str) or not base_url.startswith("https://"):
                    raise ConfigurationError(
                        f"{provider_name}/{surface_name} requires an HTTPS base_url."
                    )
                if not isinstance(model_prefix, str) or not model_prefix:
                    raise ConfigurationError(
                        f"{provider_name}/{surface_name} requires model_prefix."
                    )

            if "api_key" in modes:
                api_key_env = surface.get("api_key_env")
                if not isinstance(api_key_env, str) or not re.fullmatch(
                    r"[A-Z][A-Z0-9_]*", api_key_env
                ):
                    raise ConfigurationError(
                        f"{provider_name}/{surface_name} must declare a valid API key environment variable."
                    )
            elif surface.get("api_key_env") is not None:
                raise ConfigurationError(
                    f"{provider_name}/{surface_name} declares api_key_env without api_key mode."
                )

            if "subscription_login" in modes and not surface.get("subscription_scope"):
                raise ConfigurationError(
                    f"{provider_name}/{surface_name} must describe its subscription scope."
                )

    return registry


def validate_profile(profile_name: str, profile: dict, registry: dict) -> None:
    if not PROFILE_NAME_PATTERN.fullmatch(profile_name):
        raise ConfigurationError(f"Invalid profile name: {profile_name!r}.")
    if not isinstance(profile, dict):
        raise ConfigurationError(f"Profile {profile_name!r} must be an object.")

    required = {"provider", "surface", "model", "connection_mode"}
    missing = sorted(required - set(profile))
    if missing:
        raise ConfigurationError(
            f"Profile {profile_name!r} is missing: {', '.join(missing)}."
        )

    provider_name = profile["provider"]
    surface_name = profile["surface"]
    model = profile["model"]
    connection_mode = profile["connection_mode"]

    provider = registry["providers"].get(provider_name)
    if provider is None:
        raise ConfigurationError(
            f"Profile {profile_name!r} references unknown provider: {provider_name!r}."
        )

    surface = provider["surfaces"].get(surface_name)
    if surface is None:
        raise ConfigurationError(
            f"Profile {profile_name!r} references unknown surface "
            f"{provider_name}/{surface_name}."
        )

    if connection_mode not in surface["connection_modes"]:
        raise ConfigurationError(
            f"Profile {profile_name!r} references unsupported connection mode "
            f"{connection_mode!r} for {provider_name}/{surface_name}."
        )

    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ConfigurationError(
            f"Profile {profile_name!r} model must be null or a non-empty string."
        )

    if surface["integration"] in {"openhands_llm_openai_compatible", "openhands_llm_ollama"} and model is None:
        raise ConfigurationError(
            f"Profile {profile_name!r} requires an explicit model for "
            "OpenHands OpenAI-compatible transport."
        )


def validate_profile_config(config_path: Path, registry: dict | None = None) -> dict:
    config = load_json(config_path)
    if config.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ConfigurationError("Unsupported AI profile schema version.")

    profiles = config.get("profiles")
    active_profile = config.get("active_profile")
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigurationError("AI profile config must contain profiles.")
    if not isinstance(active_profile, str) or not active_profile:
        raise ConfigurationError("AI profile config must declare an active_profile.")
    if active_profile not in profiles:
        raise ConfigurationError(
            f"active_profile does not exist: {active_profile!r}."
        )

    registry = registry or load_registry()
    for name, profile in profiles.items():
        validate_profile(name, profile, registry)

    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "profile_config",
        type=Path,
        nargs="?",
        help="Path to a user AI profile JSON file. Omit to validate only the backend registry.",
    )
    args = parser.parse_args()

    registry = load_registry()
    if args.profile_config is not None:
        validate_profile_config(args.profile_config, registry)

    if args.profile_config is None:
        print(f"AI backend registry: {len(registry['providers'])} providers validated.")
    else:
        print(f"AI profile configuration validated: {args.profile_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
