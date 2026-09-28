#!/usr/bin/env python3
"""Run one managed Aegis project task through the verified OpenHands boundary."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from implementation_readiness import (
    ImplementationReadiness,
    ImplementationReadinessError,
    evaluate_readiness,
)
from openhands_execution import (
    OpenHandsExecutionClient,
    OpenHandsExecutionRequest,
)
from preflight_runtime import RuntimePreflightError, preflight
from render_openhands_profile import render_profile
from work_item_lifecycle import (
    GitHubIssuesProvider,
    LifecycleState,
    Traceability,
    WorkItemLifecycleError,
    WorkItemProvider,
)

DEFAULT_OLLAMA_VERSION = "0.34.3"
DEFAULT_MODEL = "gemma4:31b"
DEFAULT_OPENHANDS_VERSION = "1.49.5"
DEFAULT_MAX_ITERATIONS = 500
DEFAULT_TIMEOUT_SECONDS = 3600.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_CONTAINER_WORKSPACE_ROOT = "/projects"
DEFAULT_PROFILE_CONFIG = (
    Path(__file__).resolve().parents[1] / "templates" / "ai-profiles.example.json"
)
PROTECTED_BRANCHES = frozenset({"main", "develop"})
TASK_BRANCH_PATTERN = re.compile(r"^ai/(feature|fix|refactor|chore)/[A-Za-z0-9._-]+$")
WORK_ITEM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
GIT_RUNNER = Callable[..., subprocess.CompletedProcess[str]]


class AegisOrchestratorError(RuntimeError):
    """Raised when managed execution cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class GitState:
    """Git state captured at a safety checkpoint."""

    root: Path
    branch: str
    head: str
    dirty: bool
    status_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    """Explicit inputs for one managed project execution."""

    project_path: Path
    work_item_id: str
    task: str
    agent_server_url: str
    container_workspace: str
    profile_config: Path = DEFAULT_PROFILE_CONFIG
    profile_name: str = "development-local"
    base_branch: str = "ai/integration"
    branch_name: str | None = None
    branch_kind: str = "feature"
    expected_ollama_version: str = DEFAULT_OLLAMA_VERSION
    expected_model: str = DEFAULT_MODEL
    expected_openhands_version: str = DEFAULT_OPENHANDS_VERSION
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    session_api_key: str | None = None
    allow_no_change: bool = False
    evidence_path: Path | None = None
    evidence_ref: str | None = None
    work_item_provider: WorkItemProvider | None = None


def _run_git(root: Path, args: tuple[str, ...], *, check: bool = True,
             run_command: GIT_RUNNER = subprocess.run) -> subprocess.CompletedProcess[str]:
    try:
        return run_command(
            ["git", "-C", str(root), *args],
            check=check,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AegisOrchestratorError(f"Git command failed: git {' '.join(args)}.") from exc


def _git_stdout(root: Path, args: tuple[str, ...], *,
                run_command: GIT_RUNNER = subprocess.run) -> str:
    return _run_git(root, args, run_command=run_command).stdout.strip()


def inspect_git_state(project_path: Path, *,
                      run_command: GIT_RUNNER = subprocess.run) -> GitState:
    """Verify repository root, branch ownership, HEAD, and worktree cleanliness."""
    project = project_path.expanduser().resolve()
    if not project.is_dir():
        raise AegisOrchestratorError(f"Project path does not exist: {project}")
    root = Path(_git_stdout(project, ("rev-parse", "--show-toplevel"), run_command=run_command)).resolve()
    if root != project:
        raise AegisOrchestratorError("Project path must be the Git repository root.")
    branch = _git_stdout(project, ("symbolic-ref", "--short", "HEAD"), run_command=run_command)
    if not branch:
        raise AegisOrchestratorError("Detached HEAD is not allowed for managed execution.")
    if branch in PROTECTED_BRANCHES:
        raise AegisOrchestratorError(f"Protected branch {branch!r} cannot be modified by the orchestrator.")
    head = _git_stdout(project, ("rev-parse", "HEAD"), run_command=run_command)
    status_text = _git_stdout(project, ("status", "--porcelain=v1"), run_command=run_command)
    status_lines = tuple(line for line in status_text.splitlines() if line)
    return GitState(root, branch, head, bool(status_lines), status_lines)


def normalize_work_item_id(value: str) -> str:
    """Normalize an issue-style identifier for use in evidence and branch names."""
    normalized = value.strip().lstrip("#")
    if not normalized or not WORK_ITEM_PATTERN.fullmatch(normalized):
        raise AegisOrchestratorError("work_item_id contains unsupported characters.")
    return normalized


def build_task_branch_name(work_item_id: str, *, branch_kind: str = "feature",
                           suffix: str = "execution") -> str:
    """Build the task-branch name required by the Aegis branch policy."""
    work_item = normalize_work_item_id(work_item_id)
    if branch_kind not in {"feature", "fix", "refactor", "chore"}:
        raise AegisOrchestratorError("branch_kind must be feature, fix, refactor, or chore.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", suffix):
        raise AegisOrchestratorError("branch suffix is invalid.")
    branch = f"ai/{branch_kind}/{work_item}-{suffix}"
    if not TASK_BRANCH_PATTERN.fullmatch(branch):
        raise AegisOrchestratorError("Generated task branch name is invalid.")
    return branch


def create_task_branch(state: GitState, *, base_branch: str, task_branch: str,
                       run_command: GIT_RUNNER = subprocess.run) -> GitState:
    """Create a fresh AI task branch only from a clean autonomous base."""
    if state.dirty:
        details = "; ".join(state.status_lines[:5])
        raise AegisOrchestratorError(f"Managed execution requires a clean worktree: {details}")
    if base_branch in PROTECTED_BRANCHES or not base_branch.startswith("ai/"):
        raise AegisOrchestratorError("Task branch base must be a non-protected ai/* branch.")
    if not TASK_BRANCH_PATTERN.fullmatch(task_branch):
        raise AegisOrchestratorError("Task branch does not follow the Aegis branch policy.")
    existing = _run_git(state.root, ("show-ref", "--verify", "--quiet", f"refs/heads/{task_branch}"),
                        check=False, run_command=run_command)
    if existing.returncode == 0:
        raise AegisOrchestratorError(f"Task branch already exists: {task_branch}.")
    base = _run_git(state.root, ("show-ref", "--verify", "--quiet", f"refs/heads/{base_branch}"),
                    check=False, run_command=run_command)
    if base.returncode != 0:
        raise AegisOrchestratorError(f"Configured base branch does not exist locally: {base_branch}.")
    _run_git(state.root, ("switch", "--create", task_branch, base_branch), run_command=run_command)
    created = inspect_git_state(state.root, run_command=run_command)
    if created.branch != task_branch:
        raise AegisOrchestratorError(f"Git switched to unexpected branch {created.branch!r}.")
    return created


def validate_container_workspace(workspace: str) -> str:
    """Validate the explicit OpenHands container-side workspace path."""
    value = workspace.strip()
    path = PurePosixPath(value)
    if not value or "\x00" in value or not path.is_absolute() or any(part == ".." for part in path.parts):
        raise AegisOrchestratorError("container_workspace must be an absolute POSIX path without traversal.")
    if path == PurePosixPath("/"):
        raise AegisOrchestratorError("container_workspace must identify a project path.")
    return value.rstrip("/")


def build_execution_task(user_task: str, work_item_id: str) -> str:
    """Wrap the task in a boundary that leaves Git lifecycle control with Aegis."""
    task = user_task.strip()
    if not task:
        raise AegisOrchestratorError("task must not be empty.")
    work_item = normalize_work_item_id(work_item_id)
    return (
        "You are executing one managed Aegis engineering work item.\n"
        f"Work item: {work_item}\n\n"
        "Aegis controls the Git lifecycle around this execution.\n"
        "Do not commit changes, create commits, amend commits, push, pull, fetch, "
        "change remotes, switch branches, reset, rebase, or rewrite Git history.\n"
        "Do not access credentials, secret stores, GitHub, sibling repositories, "
        "or paths outside the supplied project workspace.\n"
        "Make the requested implementation changes in the current task branch and "
        "leave them uncommitted for Aegis review.\n\n"
        "--- BEGIN USER TASK ---\n"
        f"{task}\n"
        "--- END USER TASK ---\n"
    )


def _build_agent_settings(profile_config: Path, profile_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rendered = render_profile(profile_config, profile_name)
    expected = {"provider": "ollama", "surface": "local", "openhands_agent_kind": "llm"}
    if any(rendered.get(key) != value for key, value in expected.items()):
        raise AegisOrchestratorError("Selected profile is not the validated local Ollama OpenHands profile.")
    model, base_url, api_key = (rendered.get("llm_model"), rendered.get("llm_base_url"), rendered.get("api_key_placeholder"))
    if not all(isinstance(value, str) and value for value in (model, base_url, api_key)):
        raise AegisOrchestratorError("Rendered profile is missing required OpenHands LLM settings.")
    return (
        {"agent_kind": "openhands", "agent": "CodeActAgent",
         "llm": {"model": model, "base_url": base_url, "api_key": api_key},
         "tools": None, "enable_sub_agents": False},
        rendered,
    )


def _verify_post_execution(state: GitState, task_branch: str, *, allow_no_change: bool,
                           run_command: GIT_RUNNER = subprocess.run) -> GitState:
    final = inspect_git_state(state.root, run_command=run_command)
    if final.branch != task_branch:
        raise AegisOrchestratorError(f"OpenHands changed the Git branch to {final.branch!r}.")
    if final.head != state.head:
        raise AegisOrchestratorError("OpenHands changed Git HEAD; agent-side commits or history rewrites are not allowed.")
    if not allow_no_change and not final.dirty:
        raise AegisOrchestratorError("OpenHands finished but produced no inspectable working-tree changes.")
    try:
        _run_git(state.root, ("diff", "--check"), run_command=run_command)
    except AegisOrchestratorError as exc:
        raise AegisOrchestratorError("Git diff --check failed after OpenHands execution.") from exc
    return final


def _resolve_evidence_ref(config: OrchestratorConfig) -> str | None:
    if config.evidence_ref is not None:
        value = config.evidence_ref.strip()
        if not value:
            raise AegisOrchestratorError("evidence_ref must not be empty when supplied.")
        return value
    if config.evidence_path is not None:
        return config.evidence_path.name
    return None


def _sync_blocked_work_item(
    provider: WorkItemProvider,
    work_item_id: str,
    *,
    failure_class: str,
    conversation_id: str | None,
    outcome: str | None = None,
) -> None:
    """Record an execution failure without leaking the exception contents."""
    try:
        provider.transition(
            work_item_id,
            LifecycleState.BLOCKED,
            expected_state=LifecycleState.IN_PROGRESS,
        )
        details = [
            "<!-- aegis:execution-failure:v1 -->",
            "## Aegis execution blocked",
            f"- **Work item:** {work_item_id}",
            f"- **Failure class:** {failure_class}",
        ]
        if conversation_id is not None:
            details.append(f"- **OpenHands conversation:** {conversation_id}")
        if outcome is not None:
            details.append(f"- **Execution outcome:** {outcome}")
        provider.comment(work_item_id, "\n".join(details))
    except WorkItemLifecycleError as sync_error:
        raise AegisOrchestratorError(
            "Execution failed and Aegis could not synchronize the work item "
            f"to blocked state: {sync_error}"
        ) from sync_error


def _sync_ready_to_in_progress(
    provider: WorkItemProvider,
    work_item_id: str,
    task_branch: str,
) -> None:
    provider.attach_traceability(
        work_item_id,
        Traceability(branch=task_branch),
    )
    provider.transition(
        work_item_id,
        LifecycleState.IN_PROGRESS,
        expected_state=LifecycleState.READY,
    )


def _sync_success_to_verification(
    provider: WorkItemProvider,
    work_item_id: str,
    task_branch: str,
    conversation_id: str,
    evidence_ref: str | None,
) -> None:
    provider.attach_traceability(
        work_item_id,
        Traceability(
            branch=task_branch,
            conversation_id=conversation_id,
            evidence_ref=evidence_ref,
        ),
    )
    provider.transition(
        work_item_id,
        LifecycleState.VERIFICATION,
        expected_state=LifecycleState.IN_PROGRESS,
    )


def orchestrate(config: OrchestratorConfig, *, preflight_fn: Callable[..., dict[str, Any]] = preflight,
                execute_fn: Callable[[OpenHandsExecutionRequest], Any] | None = None,
                run_command: GIT_RUNNER = subprocess.run) -> dict[str, Any]:
    """Run one managed project task and return verified execution evidence."""
    work_item = normalize_work_item_id(config.work_item_id)
    container_workspace = validate_container_workspace(config.container_workspace)
    evidence_ref = _resolve_evidence_ref(config)
    if not config.task.strip():
        raise AegisOrchestratorError("task must not be empty.")
    if not config.base_branch.startswith("ai/") or config.base_branch in PROTECTED_BRANCHES:
        raise AegisOrchestratorError("base_branch must be a non-protected ai/* branch.")
    if config.max_iterations <= 0 or config.timeout_seconds <= 0 or config.poll_interval_seconds <= 0:
        raise AegisOrchestratorError("iteration and timing values must be greater than zero.")

    initial = inspect_git_state(config.project_path, run_command=run_command)
    if initial.dirty:
        raise AegisOrchestratorError("Target project must be clean before managed execution.")

    provider = config.work_item_provider
    current_work_item = None
    if provider is not None:
        current_work_item = provider.get(work_item)
        if current_work_item.state != LifecycleState.READY:
            raise AegisOrchestratorError(
                "Managed execution requires the work item to be ready; "
                f"got {current_work_item.state.value}."
            )

    readiness: ImplementationReadiness | None = None
    readiness_inputs = (
        config.work_item_kind,
        config.work_item_document,
        config.version_evidence_ref,
        config.architecture_required,
    )
    if provider is not None or any(value is not None for value in readiness_inputs):
        if any(value is None for value in readiness_inputs):
            raise AegisOrchestratorError(
                "Implementation readiness requires explicit work-item kind, "
                "work-item document, version evidence, and architecture applicability."
            )
        try:
            readiness = evaluate_readiness(
                config.work_item_document,
                config.work_item_kind,
                project_root=config.project_path,
                version_evidence_ref=config.version_evidence_ref,
                architecture_required=config.architecture_required,
                work_item_provider=provider,
                work_item_id=work_item,
            )
        except ImplementationReadinessError as exc:
            raise AegisOrchestratorError(
                f"Implementation readiness check failed: {exc}"
            ) from exc
        if not readiness.ready:
            raise AegisOrchestratorError(
                "Implementation readiness is blocked; managed execution must not start."
            )

    preflight_result = preflight_fn(
        config.profile_config,
        config.profile_name,
        openhands_agent_server_url=config.agent_server_url,
        openhands_agent_server_api_key=config.session_api_key,
    )
    if preflight_result.get("ollama_version") != config.expected_ollama_version:
        raise AegisOrchestratorError("Verified Ollama version does not match the execution contract.")
    if preflight_result.get("model") != config.expected_model:
        raise AegisOrchestratorError("Verified Ollama model does not match the execution contract.")
    server = preflight_result.get("openhands_agent_server")
    if not isinstance(server, Mapping) or server.get("version") != config.expected_openhands_version:
        raise AegisOrchestratorError("Verified OpenHands Agent Server version does not match the execution contract.")
    if server.get("conversation_runtime") != "local":
        raise AegisOrchestratorError("Managed execution requires OpenHands conversation_runtime=local.")

    agent_settings, rendered_profile = _build_agent_settings(
        config.profile_config,
        config.profile_name,
    )
    if agent_settings["llm"].get("model") != f"openai/{config.expected_model}":
        raise AegisOrchestratorError("Rendered OpenHands model does not match the execution contract.")

    task_branch = config.branch_name or build_task_branch_name(
        work_item,
        branch_kind=config.branch_kind,
    )
    task_state = create_task_branch(
        initial,
        base_branch=config.base_branch,
        task_branch=task_branch,
        run_command=run_command,
    )

    if provider is not None:
        _sync_ready_to_in_progress(provider, work_item, task_branch)

    request = OpenHandsExecutionRequest(
        server_url=config.agent_server_url,
        workspace=container_workspace,
        task=build_execution_task(config.task, work_item),
        agent_settings=agent_settings,
        confirmation_policy={"kind": "ConfirmRisky"},
        expected_agent_server_version=config.expected_openhands_version,
        max_iterations=config.max_iterations,
        timeout_seconds=config.timeout_seconds,
        poll_interval_seconds=config.poll_interval_seconds,
        workspace_root=DEFAULT_CONTAINER_WORKSPACE_ROOT,
        session_api_key=config.session_api_key,
    )

    try:
        client = OpenHandsExecutionClient()
        result = execute_fn(request) if execute_fn else client.execute(request)
        if result.outcome != "finished":
            raise AegisOrchestratorError(
                f"OpenHands execution did not finish successfully: "
                f"{result.outcome} ({result.execution_status}). "
                f"Conversation: {result.conversation_id}"
            )
        final = _verify_post_execution(
            task_state,
            task_branch,
            allow_no_change=config.allow_no_change,
            run_command=run_command,
        )
    except Exception as exc:
        if provider is not None:
            _sync_blocked_work_item(
                provider,
                work_item,
                failure_class=type(exc).__name__,
                conversation_id=getattr(exc, "conversation_id", None),
                outcome=(
                    result.outcome
                    if "result" in locals() and getattr(result, "outcome", None) is not None
                    else None
                ),
            )
        raise

    work_item_sync: dict[str, Any] | None = None
    if provider is not None:
        _sync_success_to_verification(
            provider,
            work_item,
            task_branch,
            result.conversation_id,
            evidence_ref,
        )
        work_item_sync = {
            "provider": current_work_item.provider,
            "state_before_execution": current_work_item.state.value,
            "state_after_execution": LifecycleState.VERIFICATION.value,
            "verified": True,
        }

    evidence: dict[str, Any] = {
        "status": "verified",
        "work_item_id": work_item,
        "branch": {
            "base": config.base_branch,
            "task": task_branch,
            "starting_head": task_state.head,
            "final_head": final.head,
            "head_unchanged": task_state.head == final.head,
        },
        "profile": rendered_profile,
        "runtime": {
            "ollama_version": preflight_result["ollama_version"],
            "model": preflight_result["model"],
            "openhands": dict(server),
        },
        "execution": {
            "conversation_id": result.conversation_id,
            "status": result.execution_status,
            "outcome": result.outcome,
            "events": {"count": len(result.events)},
        },
        "workspace": {
            "container_path": container_workspace,
            "host_project": str(task_state.root),
        },
        "git": {
            "working_tree_changed": final.dirty,
            "status_lines": list(final.status_lines),
            "diff_check": "passed",
        },
    }
    if readiness is not None:
        evidence["implementation_readiness"] = {
            "ready": readiness.ready,
            "work_item_kind": readiness.work_item_kind,
            "architecture_required": readiness.architecture_required,
            "version_evidence_ref": readiness.version_evidence_ref,
            "composition_steps": list(readiness.composition_steps),
            "observations": [
                {
                    "check": item.check,
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in readiness.observations
            ],
        }
    if work_item_sync is not None:
        evidence["work_item"] = work_item_sync

    if config.evidence_path is not None:
        path = config.evidence_path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence["evidence_path"] = str(path)
    return evidence


def parse_args() -> OrchestratorConfig:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run one managed Aegis project task through OpenHands.")
    parser.add_argument("project", type=Path)
    parser.add_argument("work_item_id")
    parser.add_argument("task")
    parser.add_argument("--work-item-kind")
    parser.add_argument("--work-item-document", type=Path)
    parser.add_argument("--version-evidence-ref")
    architecture = parser.add_mutually_exclusive_group()
    architecture.add_argument("--architecture-required", action="store_true")
    architecture.add_argument("--architecture-not-required", action="store_true")
    parser.add_argument("--agent-server-url", required=True)
    parser.add_argument("--container-workspace", required=True)
    parser.add_argument("--profile-config", type=Path, default=DEFAULT_PROFILE_CONFIG)
    parser.add_argument("--profile-name", default="development-local")
    parser.add_argument("--base-branch", default="ai/integration")
    parser.add_argument("--branch-name")
    parser.add_argument("--branch-kind", choices=("feature", "fix", "refactor", "chore"), default="feature")
    parser.add_argument("--expected-ollama-version", default=DEFAULT_OLLAMA_VERSION)
    parser.add_argument("--expected-model", default=DEFAULT_MODEL)
    parser.add_argument("--expected-openhands-version", default=DEFAULT_OPENHANDS_VERSION)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--session-api-key-env", default="AEGIS_OPENHANDS_AGENT_SERVER_API_KEY")
    parser.add_argument("--allow-no-change", action="store_true")
    parser.add_argument("--evidence-path", type=Path)
    parser.add_argument(
        "--evidence-ref",
        help="Durable relative reference attached to the work item evidence.",
    )
    parser.add_argument(
        "--work-item-repository",
        help="GitHub repository in owner/name form. Omit to disable work-item synchronization.",
    )
    parser.add_argument(
        "--work-item-token-env",
        default="GITHUB_TOKEN",
        help="Environment variable containing the GitHub Issues token.",
    )
    args = parser.parse_args()
    key = os.environ.get(args.session_api_key_env)
    work_item_provider = None
    if args.work_item_repository:
        token = os.environ.get(args.work_item_token_env, "")
        try:
            work_item_provider = GitHubIssuesProvider(
                args.work_item_repository,
                token,
            )
        except WorkItemLifecycleError as exc:
            parser.error(str(exc))
    if args.architecture_required:
        architecture_required = True
    elif args.architecture_not_required:
        architecture_required = False
    else:
        architecture_required = None

    if args.work_item_repository and (
        args.work_item_kind is None
        or args.work_item_document is None
        or args.version_evidence_ref is None
        or architecture_required is None
    ):
        parser.error(
            "managed execution requires --work-item-kind, --work-item-document, "
            "--version-evidence-ref, and an architecture applicability flag"
        )

    return OrchestratorConfig(
        project_path=args.project, work_item_id=args.work_item_id,
        work_item_kind=args.work_item_kind,
        work_item_document=args.work_item_document,
        version_evidence_ref=args.version_evidence_ref,
        architecture_required=architecture_required,
        task=args.task,
        agent_server_url=args.agent_server_url, container_workspace=args.container_workspace,
        profile_config=args.profile_config, profile_name=args.profile_name, base_branch=args.base_branch,
        branch_name=args.branch_name, branch_kind=args.branch_kind,
        expected_ollama_version=args.expected_ollama_version, expected_model=args.expected_model,
        expected_openhands_version=args.expected_openhands_version, max_iterations=args.max_iterations,
        timeout_seconds=args.timeout, poll_interval_seconds=args.poll_interval, session_api_key=key,
        allow_no_change=args.allow_no_change,
        evidence_path=args.evidence_path,
        evidence_ref=args.evidence_ref,
        work_item_provider=work_item_provider,
    )


def main() -> int:
    try:
        evidence = orchestrate(parse_args())
    except (AegisOrchestratorError, RuntimePreflightError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
