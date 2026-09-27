#!/usr/bin/env python3
"""Run one isolated live Aegis-to-OpenHands smoke test.

This command is intentionally destructive only inside a unique temporary directory
under the configured OpenHands workspace mount. It must never be used as a general
project execution command.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from openhands_execution import OpenHandsExecutionClient, OpenHandsExecutionRequest
from preflight_runtime import RuntimePreflightError, preflight

DEFAULT_OLLAMA_VERSION = "0.34.3"
DEFAULT_MODEL = "gemma4:31b"
DEFAULT_OPENHANDS_AGENT_SERVER_VERSION = "1.49.5"
DEFAULT_OPENHANDS_IMAGE = "ghcr.io/openhands/agent-canvas:1.23.0"
DEFAULT_OPENHANDS_CONTAINER_UID = 10001
DEFAULT_WORKSPACE_ROOT = Path.home() / "openhands_workspace"
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
EXPECTED_FILE_NAME = "Aegis-Live-E2E.txt"
EXPECTED_FILE_CONTENT = "AEGIS_LIVE_E2E_OK\n"


class LiveE2EError(RuntimeError):
    """Raised when the live smoke-test preconditions or result are invalid."""


@dataclass(frozen=True, slots=True)
class LiveE2EConfig:
    """Explicit configuration for one isolated live verification."""

    profile_config: Path
    profile_name: str
    agent_server_url: str
    host_workspace_root: Path
    openhands_container: str
    expected_ollama_version: str = DEFAULT_OLLAMA_VERSION
    expected_model: str = DEFAULT_MODEL
    expected_openhands_version: str = DEFAULT_OPENHANDS_AGENT_SERVER_VERSION
    expected_openhands_image: str = DEFAULT_OPENHANDS_IMAGE
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    agent_server_api_key: str | None = None
    configure_workspace_permissions: bool = True


def _validate_loopback_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LiveE2EError(
            "OpenHands Agent Server URL must use http(s) and include a hostname."
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LiveE2EError(
            "OpenHands Agent Server URL must not contain credentials, query, or fragment data."
        )
    if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise LiveE2EError(
            "Live local verification requires a loopback OpenHands Agent Server URL."
        )
    return value.rstrip("/")


def _inspect_container_image(
    container_name: str,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Read the configured Docker image without mutating the container."""

    try:
        result = run_command(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Config.Image}}",
                container_name,
            ],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LiveE2EError(
            f"Unable to inspect OpenHands Docker container {container_name!r}."
        ) from exc

    image = result.stdout.strip()
    if not image:
        raise LiveE2EError(
            f"Docker inspect returned no image for OpenHands container {container_name!r}."
        )
    return image


def _render_local_ollama_agent(
    profile_config: Path,
    profile_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from render_openhands_profile import render_profile

    rendered = render_profile(profile_config, profile_name)
    required = {
        "provider": "ollama",
        "surface": "local",
        "openhands_agent_kind": "llm",
    }
    for key, expected in required.items():
        if rendered.get(key) != expected:
            raise LiveE2EError(
                f"Selected profile is not the validated local Ollama execution profile: {key}."
            )

    model = rendered.get("llm_model")
    base_url = rendered.get("llm_base_url")
    api_key = rendered.get("api_key_placeholder")
    if not all(
        isinstance(value, str) and value
        for value in (model, base_url, api_key)
    ):
        raise LiveE2EError(
            "Rendered local Ollama profile is missing required OpenHands LLM settings."
        )

    agent = {
        "kind": "Agent",
        "llm": {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
        },
    }
    return agent, rendered


def _configure_workspace_permissions(
    workspace: Path,
    container_uid: int = DEFAULT_OPENHANDS_CONTAINER_UID,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Grant only the temporary workspace to the OpenHands container UID.

    The live Ubuntu runtime uses UID 10001 inside the Agent Canvas container.
    A default ACL also grants the host user access to files created by the
    container. No parent or sibling path is modified.
    """
    setfacl = shutil.which("setfacl")
    if setfacl is None:
        raise LiveE2EError(
            "Live OpenHands verification requires the 'setfacl' command "
            "(install the acl package)."
        )

    if container_uid <= 0:
        raise LiveE2EError("OpenHands container UID must be greater than zero.")

    host_uid = os.getuid()
    access_entry = f"u:{container_uid}:rwx"
    default_entries = [
        "u::rwx",
        "g::---",
        "m::rwx",
        "o::---",
        access_entry,
    ]
    if host_uid != container_uid:
        default_entries.append(f"u:{host_uid}:rwx")

    try:
        run_command(
            [setfacl, "-m", access_entry, str(workspace)],
            check=True,
            text=True,
            capture_output=True,
        )
        run_command(
            [setfacl, "-d", "-m", ",".join(default_entries), str(workspace)],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LiveE2EError(
            f"Unable to configure isolated workspace ACL for OpenHands UID "
            f"{container_uid}."
        ) from exc

def _create_workspace(host_workspace_root: Path) -> Path:
    root = host_workspace_root.expanduser().resolve()
    if not root.is_dir():
        raise LiveE2EError(
            f"Configured host OpenHands workspace root does not exist: {root}"
        )

    return Path(
        tempfile.mkdtemp(
            prefix=f".aegis-live-e2e-{uuid.uuid4().hex[:12]}-",
            dir=root,
        )
    )


def _container_workspace(workspace: Path, host_workspace_root: Path) -> str:
    root = host_workspace_root.expanduser().resolve()
    target = workspace.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise LiveE2EError(
            "Temporary workspace escaped the configured host workspace root."
        ) from exc
    if len(relative.parts) != 1:
        raise LiveE2EError(
            "Temporary live workspace must be a direct child of the configured host root."
        )
    return f"/projects/{relative.parts[0]}"


def _task_text() -> str:
    return (
        "You are running a controlled Aegis live runtime smoke test in an "
        "isolated temporary workspace.\n"
        "Modify only the current workspace. Do not access sibling directories, "
        "host resources, GitHub, secrets, or any path outside the current "
        "workspace. Do not modify or create anything except the one requested "
        "file.\n\n"
        f"Create exactly one file named {EXPECTED_FILE_NAME!r} with exactly "
        f"this single line:\n{EXPECTED_FILE_CONTENT.rstrip()}\n\n"
        "Do not create any other file. After the file is written, report completion."
    )


def _verify_workspace_artifact(workspace: Path) -> dict[str, Any]:
    if not workspace.is_dir() or workspace.is_symlink():
        raise LiveE2EError(
            "Temporary live workspace is no longer a normal directory."
        )

    entries = sorted(workspace.iterdir(), key=lambda item: item.name)
    entry_names = {entry.name for entry in entries}
    allowed_names = {EXPECTED_FILE_NAME, ".git"}
    if not entry_names.issubset(allowed_names) or EXPECTED_FILE_NAME not in entry_names:
        names = [entry.name for entry in entries]
        raise LiveE2EError(
            f"Live smoke test produced an unexpected workspace shape: {names!r}."
        )

    git_metadata = workspace / ".git"
    if git_metadata in entries and (
        not git_metadata.is_dir() or git_metadata.is_symlink()
    ):
        raise LiveE2EError(
            "OpenHands Git metadata entry is not a normal directory."
        )

    artifact = workspace / EXPECTED_FILE_NAME
    if not artifact.is_file() or artifact.is_symlink():
        raise LiveE2EError(
            "Expected live smoke-test artifact is not a normal file."
        )

    content = artifact.read_text(encoding="utf-8")
    if content != EXPECTED_FILE_CONTENT:
        raise LiveE2EError(
            "Live smoke-test artifact content does not match the expected marker."
        )

    return {
        "path": artifact.name,
        "content_verified": True,
        "workspace_entry_count": len(entries),
    }


def _cleanup_workspace(
    workspace: Path | None,
    host_workspace_root: Path,
) -> dict[str, Any]:
    if workspace is None:
        return {"status": "not-created"}

    root = host_workspace_root.expanduser().resolve()
    if workspace.parent.resolve() != root:
        raise LiveE2EError(
            "Refusing to clean a workspace outside the configured host root."
        )

    if not workspace.exists():
        return {"status": "already-removed"}

    if workspace.is_symlink() or workspace.is_file():
        workspace.unlink()
    elif workspace.is_dir():
        shutil.rmtree(workspace)
    else:
        raise LiveE2EError(
            "Temporary workspace changed into an unsupported filesystem object."
        )

    return {"status": "removed" if not workspace.exists() else "failed"}


def _event_summary(
    events: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    types = Counter(
        event.get("type", "unknown")
        for event in events
        if isinstance(event, Mapping)
    )
    ids = [
        event.get("id")
        for event in events
        if isinstance(event, Mapping) and event.get("id")
    ]
    return {
        "count": len(events),
        "type_counts": dict(sorted(types.items())),
        "first_id": ids[0] if ids else None,
        "last_id": ids[-1] if ids else None,
    }


def run_live_smoke_test(
    config: LiveE2EConfig,
    preflight_fn: Callable[..., dict[str, Any]] = preflight,
    execute_fn: Callable[[OpenHandsExecutionRequest], Any] | None = None,
    inspect_image_fn: Callable[[str], str] = _inspect_container_image,
    render_agent_fn: Callable[
        [Path, str], tuple[dict[str, Any], dict[str, Any]]
    ] = _render_local_ollama_agent,
) -> dict[str, Any]:
    """Execute and verify one isolated live task, then remove its workspace."""

    profile_config = config.profile_config.resolve()
    agent_server_url = _validate_loopback_url(config.agent_server_url)

    if config.max_iterations <= 0:
        raise LiveE2EError("max_iterations must be greater than zero.")
    if config.timeout_seconds <= 0 or config.poll_interval_seconds <= 0:
        raise LiveE2EError(
            "timeout_seconds and poll_interval_seconds must be greater than zero."
        )
    if not config.expected_ollama_version.strip():
        raise LiveE2EError("expected_ollama_version must not be empty.")
    if not config.expected_model.strip():
        raise LiveE2EError("expected_model must not be empty.")
    if not config.expected_openhands_version.strip():
        raise LiveE2EError("expected_openhands_version must not be empty.")
    if not config.expected_openhands_image.strip():
        raise LiveE2EError("expected_openhands_image must not be empty.")

    actual_image = inspect_image_fn(config.openhands_container)
    if actual_image != config.expected_openhands_image:
        raise LiveE2EError(
            f"OpenHands Docker image mismatch: expected "
            f"{config.expected_openhands_image!r}, got {actual_image!r}."
        )

    preflight_result = preflight_fn(
        profile_config,
        config.profile_name,
        openhands_agent_server_url=agent_server_url,
        openhands_agent_server_api_key=config.agent_server_api_key,
    )
    if preflight_result.get("ollama_version") != config.expected_ollama_version:
        raise LiveE2EError(
            f"Ollama version mismatch: expected "
            f"{config.expected_ollama_version!r}, got "
            f"{preflight_result.get('ollama_version')!r}."
        )
    if preflight_result.get("model") != config.expected_model:
        raise LiveE2EError(
            f"Ollama model mismatch: expected "
            f"{config.expected_model!r}, got "
            f"{preflight_result.get('model')!r}."
        )

    server_evidence = preflight_result.get("openhands_agent_server")
    if not isinstance(server_evidence, Mapping):
        raise LiveE2EError(
            "OpenHands Agent Server preflight evidence is missing."
        )
    if server_evidence.get("version") != config.expected_openhands_version:
        raise LiveE2EError(
            f"OpenHands Agent Server version mismatch: expected "
            f"{config.expected_openhands_version!r}, got "
            f"{server_evidence.get('version')!r}."
        )
    if server_evidence.get("conversation_runtime") != "local":
        raise LiveE2EError(
            "OpenHands Agent Server did not report conversation_runtime=local."
        )

    agent, rendered_profile = render_agent_fn(
        profile_config,
        config.profile_name,
    )
    expected_openai_model = f"openai/{config.expected_model}"
    rendered_model = agent.get("llm", {}).get("model")
    if rendered_model != expected_openai_model:
        raise LiveE2EError(
            f"OpenHands model mismatch: expected "
            f"{expected_openai_model!r}, got {rendered_model!r}."
        )
    workspace: Path | None = None
    evidence: dict[str, Any] | None = None
    try:
        workspace = _create_workspace(config.host_workspace_root)
        if config.configure_workspace_permissions:
            _configure_workspace_permissions(workspace)
        container_workspace = _container_workspace(
            workspace,
            config.host_workspace_root,
        )

        request = OpenHandsExecutionRequest(
            server_url=agent_server_url,
            workspace=container_workspace,
            task=_task_text(),
            agent=agent,
            confirmation_policy={"kind": "NeverConfirm"},
            expected_agent_server_version=config.expected_openhands_version,
            max_iterations=config.max_iterations,
            timeout_seconds=config.timeout_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
            workspace_root="/projects",
            session_api_key=config.agent_server_api_key,
        )
        client = OpenHandsExecutionClient()
        result = execute_fn(request) if execute_fn else client.execute(request)

        if result.outcome != "finished":
            raise LiveE2EError(
                f"OpenHands live smoke test did not finish successfully: "
                f"{result.outcome} ({result.execution_status}). "
                f"Conversation: {result.conversation_id}"
            )

        artifact_evidence = _verify_workspace_artifact(workspace)
        evidence = {
            "status": "verified",
            "profile": rendered_profile,
            "ollama": {
                "version": preflight_result["ollama_version"],
                "model": preflight_result["model"],
            },
            "openhands": {
                "image": actual_image,
                "server_url": agent_server_url,
                "version": server_evidence["version"],
                "sdk_version": server_evidence["sdk_version"],
                "tools_version": server_evidence["tools_version"],
                "workspace_version": server_evidence["workspace_version"],
                "build_git_sha": server_evidence.get(
                    "build_git_sha",
                    "unknown",
                ),
                "build_git_ref": server_evidence.get(
                    "build_git_ref",
                    "unknown",
                ),
                "conversation_runtime": server_evidence[
                    "conversation_runtime"
                ],
            },
            "execution": {
                "conversation_id": result.conversation_id,
                "status": result.execution_status,
                "outcome": result.outcome,
                "events": _event_summary(result.events),
            },
            "workspace": {
                "host_root": str(
                    config.host_workspace_root.expanduser().resolve()
                ),
                "container_path": container_workspace,
                "artifact": artifact_evidence,
            },
        }
        return evidence
    finally:
        cleanup = _cleanup_workspace(
            workspace,
            config.host_workspace_root,
        )
        if evidence is not None:
            evidence["workspace"]["cleanup"] = cleanup


def parse_args() -> LiveE2EConfig:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Run one isolated live Aegis-to-OpenHands smoke test."
    )
    parser.add_argument(
        "profile_config",
        type=Path,
        nargs="?",
        default=root / "templates" / "ai-profiles.example.json",
    )
    parser.add_argument(
        "profile_name",
        nargs="?",
        default="development-local",
    )
    parser.add_argument(
        "--agent-server-url",
        default=os.environ.get("AEGIS_OPENHANDS_AGENT_SERVER_URL"),
        help="Explicit loopback OpenHands Agent Server base URL.",
    )
    parser.add_argument(
        "--agent-server-api-key-env",
        default="AEGIS_OPENHANDS_AGENT_SERVER_API_KEY",
        help=(
            "Environment variable containing the optional OpenHands "
            "session API key."
        ),
    )
    parser.add_argument(
        "--host-workspace-root",
        type=Path,
        default=DEFAULT_WORKSPACE_ROOT,
        help=(
            "Host path mounted to OpenHands /projects "
            f"(default: {DEFAULT_WORKSPACE_ROOT})."
        ),
    )
    parser.add_argument("--openhands-container", default="openhands")
    parser.add_argument(
        "--expected-ollama-version",
        default=DEFAULT_OLLAMA_VERSION,
    )
    parser.add_argument(
        "--expected-model",
        default=DEFAULT_MODEL,
        help="Exact local Ollama model tag required for live verification.",
    )
    parser.add_argument(
        "--expected-openhands-version",
        default=DEFAULT_OPENHANDS_AGENT_SERVER_VERSION,
    )
    parser.add_argument(
        "--expected-openhands-image",
        default=DEFAULT_OPENHANDS_IMAGE,
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
    )
    args = parser.parse_args()

    if not args.agent_server_url:
        parser.error(
            "--agent-server-url or AEGIS_OPENHANDS_AGENT_SERVER_URL is required."
        )
    if (
        args.max_iterations <= 0
        or args.timeout <= 0
        or args.poll_interval <= 0
    ):
        parser.error(
            "iteration and timing values must be greater than zero."
        )

    api_key = os.environ.get(args.agent_server_api_key_env)
    return LiveE2EConfig(
        profile_config=args.profile_config,
        profile_name=args.profile_name,
        agent_server_url=args.agent_server_url,
        host_workspace_root=args.host_workspace_root,
        openhands_container=args.openhands_container,
        expected_ollama_version=args.expected_ollama_version,
        expected_model=args.expected_model,
        expected_openhands_version=args.expected_openhands_version,
        expected_openhands_image=args.expected_openhands_image,
        max_iterations=args.max_iterations,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
        agent_server_api_key=api_key,
    )


def main() -> int:
    try:
        evidence = run_live_smoke_test(parse_args())
    except (LiveE2EError, RuntimePreflightError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
