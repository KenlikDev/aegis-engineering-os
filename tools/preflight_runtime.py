#!/usr/bin/env python3
"""Verify the selected local AI runtime without mutating the target project."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from validate_ai_config import load_registry, validate_profile_config


DEFAULT_TIMEOUT_SECONDS = 5


class RuntimePreflightError(RuntimeError):
    """Raised when the selected local runtime cannot be verified."""


def _request_json(
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePreflightError(f"Unable to verify local runtime at {url}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimePreflightError(f"Runtime endpoint returned a non-object JSON document: {url}")
    return payload


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _get_ollama_models(base_url: str, timeout: int) -> list[dict[str, Any]]:
    payload = _request_json(f"{base_url}/api/tags", timeout)
    models = payload.get("models")
    if not isinstance(models, list):
        raise RuntimePreflightError("Ollama /api/tags response does not contain a models list.")
    return [model for model in models if isinstance(model, dict)]


def preflight(
    profile_config: Path,
    profile_name: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    openhands_agent_server_url: str | None = None,
    openhands_agent_server_api_key: str | None = None,
) -> dict[str, Any]:
    registry = load_registry()
    config = validate_profile_config(profile_config, registry)

    profile = config["profiles"].get(profile_name)
    if profile is None:
        raise RuntimePreflightError(f"Unknown AI profile: {profile_name!r}.")

    surface = registry["providers"][profile["provider"]]["surfaces"][profile["surface"]]
    integration = surface["integration"]

    if integration != "openhands_llm_ollama":
        raise RuntimePreflightError(
            "Live runtime preflight currently supports only the local Ollama integration."
        )

    model = profile["model"]
    if not isinstance(model, str) or not model:
        raise RuntimePreflightError("The selected local Ollama profile must declare an exact model tag.")

    base_url = _normalize_base_url(surface["ollama_base_url"])
    version = _request_json(f"{base_url}/api/version", timeout).get("version")
    if not isinstance(version, str) or not version:
        raise RuntimePreflightError("Ollama /api/version response does not contain a version string.")

    models = _get_ollama_models(base_url, timeout)
    available_models = sorted(
        name
        for name in (item.get("name") for item in models)
        if isinstance(name, str) and name
    )

    if model not in available_models:
        raise RuntimePreflightError(
            f"Selected Ollama model {model!r} is not installed. "
            f"Available models: {', '.join(available_models) or '(none)'}."
        )

    result = {
        "status": "verified",
        "provider": profile["provider"],
        "surface": profile["surface"],
        "integration": integration,
        "connection_mode": profile["connection_mode"],
        "model": model,
        "ollama_base_url": base_url,
        "ollama_version": version,
        "model_available": True,
    }

    if openhands_agent_server_url:
        agent_server_base_url = _normalize_base_url(openhands_agent_server_url)

        alive = _request_json(f"{agent_server_base_url}/alive", timeout)
        if alive.get("status") != "ok":
            raise RuntimePreflightError(
                "OpenHands Agent Server /alive did not report status=ok."
            )

        ready = _request_json(f"{agent_server_base_url}/ready", timeout)
        if ready.get("status") != "ready":
            raise RuntimePreflightError(
                "OpenHands Agent Server is reachable but not ready."
            )

        server_info = _request_json(
            f"{agent_server_base_url}/server_info",
            timeout,
        )
        conversation_runtime = server_info.get("conversation_runtime")
        if conversation_runtime != "local":
            raise RuntimePreflightError(
                "OpenHands Agent Server must report conversation_runtime=local "
                "for the local runtime boundary."
            )

        for field in (
            "version",
            "sdk_version",
            "tools_version",
            "workspace_version",
        ):
            if not isinstance(server_info.get(field), str) or not server_info[field]:
                raise RuntimePreflightError(
                    f"OpenHands Agent Server /server_info is missing {field}."
                )

        server_headers = (
            {"X-Session-API-Key": openhands_agent_server_api_key}
            if openhands_agent_server_api_key
            else None
        )
        openai_models = _request_json(
            f"{agent_server_base_url}/v1/models",
            timeout,
            headers=server_headers,
        )
        model_entries = openai_models.get("data")
        if not isinstance(model_entries, list):
            raise RuntimePreflightError(
                "OpenHands Agent Server /v1/models response does not contain a data list."
            )

        exposed_model_ids = sorted(
            item.get("id")
            for item in model_entries
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        )
        accepted_model_ids = {model, f"openai/{model}"}
        matching_model_ids = sorted(
            model_id for model_id in exposed_model_ids if model_id in accepted_model_ids
        )
        if not matching_model_ids:
            raise RuntimePreflightError(
                f"Selected model {model!r} is not exposed by the OpenHands "
                f"OpenAI-compatible /v1/models endpoint. "
                f"Available models: {', '.join(exposed_model_ids) or '(none)'}."
            )

        result["openhands_agent_server"] = {
            "status": "verified",
            "openai_compatible_model": matching_model_ids[0],
            "openai_compatible_model_surface": "verified",
            "base_url": agent_server_base_url,
            "version": server_info["version"],
            "sdk_version": server_info["sdk_version"],
            "tools_version": server_info["tools_version"],
            "workspace_version": server_info["workspace_version"],
            "build_git_sha": server_info.get("build_git_sha", "unknown"),
            "build_git_ref": server_info.get("build_git_ref", "unknown"),
            "conversation_runtime": conversation_runtime,
        }

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the selected local Ollama runtime for an Aegis AI profile."
    )
    parser.add_argument("profile_config", type=Path)
    parser.add_argument("profile_name")
    parser.add_argument(
        "--agent-server-url",
        default=os.environ.get("AEGIS_OPENHANDS_AGENT_SERVER_URL"),
        help="Explicit OpenHands Agent Server base URL; may also be set via AEGIS_OPENHANDS_AGENT_SERVER_URL.",
    )
    parser.add_argument(
        "--agent-server-api-key-env",
        default="AEGIS_OPENHANDS_AGENT_SERVER_API_KEY",
        help="Environment variable containing the optional OpenHands Agent Server session API key.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero.")

    agent_server_api_key = None
    if args.agent_server_url:
        agent_server_api_key = os.environ.get(args.agent_server_api_key_env)

    try:
        result = preflight(
            args.profile_config,
            args.profile_name,
            args.timeout,
            args.agent_server_url,
            agent_server_api_key,
        )
    except (ValueError, RuntimePreflightError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
