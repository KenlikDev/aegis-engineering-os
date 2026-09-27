#!/usr/bin/env python3
"""Render an Aegis AI profile into OpenHands-oriented settings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from validate_ai_config import load_registry, validate_profile_config


def render_profile(profile_config: Path, profile_name: str) -> dict[str, Any]:
    """Render one validated Aegis AI profile into OpenHands settings."""

    registry = load_registry()
    config = validate_profile_config(profile_config, registry)

    profile = config["profiles"].get(profile_name)
    if profile is None:
        raise ValueError(f"unknown profile {profile_name!r}.")

    surface = registry["providers"][profile["provider"]]["surfaces"][profile["surface"]]
    integration = surface["integration"]

    result: dict[str, Any] = {
        "provider": profile["provider"],
        "surface": profile["surface"],
        "connection_mode": profile["connection_mode"],
        "integration": integration,
    }

    if integration == "openhands_acp":
        result.update(
            {
                "openhands_agent_kind": "acp",
                "acp_server": profile["surface"],
                "acp_model": profile["model"],
            }
        )
    elif integration == "openhands_llm_ollama":
        result.update(
            {
                "openhands_agent_kind": "llm",
                "llm_model": f'openai/{profile["model"]}',
                "llm_base_url": f'{surface["docker_ollama_base_url"].rstrip("/")}/v1',
                "api_key_placeholder": "local-llm",
            }
        )
    elif integration == "openhands_llm_openai_compatible":
        result.update(
            {
                "openhands_agent_kind": "llm",
                "llm_model": f'{surface["model_prefix"]}{profile["model"]}',
                "llm_base_url": surface["base_url"],
                "api_key_env": surface["api_key_env"],
            }
        )
    else:
        result.update(
            {
                "openhands_agent_kind": "custom",
                "note": "Use a provider-specific agent or ACP adapter; Aegis does not invent a transport.",
            }
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_config", type=Path)
    parser.add_argument("profile_name")
    args = parser.parse_args()

    try:
        result = render_profile(args.profile_config, args.profile_name)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
