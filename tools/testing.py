#!/usr/bin/env python3
"""Run the project's explicit testing and quality-gate contract."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quality_gates import (
    DEFAULT_MANIFEST,
    QualityGate,
    QualityGateError,
    CommandRunner,
    execute_quality_gates,
    load_quality_gates,
    run_with_optional_work_item,
)
from work_item_lifecycle import (
    GitHubIssuesProvider,
    LifecycleState,
    WorkItemLifecycleError,
    WorkItemProvider,
)


class TestingWorkflowError(RuntimeError):
    """Raised when the testing workflow cannot establish a safe contract."""


@dataclass(frozen=True, slots=True)
class TestingPlan:
    """Validated testing contract before execution."""

    project: str
    manifest: str
    gates: tuple[QualityGate, ...]
    work_item_id: str | None
    lifecycle_state: str | None

    @property
    def required_gate_ids(self) -> tuple[str, ...]:
        return tuple(gate.id for gate in self.gates if gate.required)


def prepare_testing(
    project: str | Path,
    manifest: str | Path = DEFAULT_MANIFEST,
    *,
    work_item_provider: WorkItemProvider | None = None,
    work_item_id: str | None = None,
) -> TestingPlan:
    """Validate an explicit testing contract without executing commands."""
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise TestingWorkflowError(f"Project directory does not exist: {root}")

    manifest_path = Path(manifest).expanduser()
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest_path = manifest_path.resolve()

    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise TestingWorkflowError(
            "Testing manifest must live inside the project root."
        ) from exc

    try:
        gates = load_quality_gates(manifest_path)
    except QualityGateError as exc:
        raise TestingWorkflowError(str(exc)) from exc

    lifecycle_state: str | None = None
    if work_item_provider is not None:
        if not work_item_id:
            raise TestingWorkflowError(
                "work_item_id is required when work-item synchronization is enabled."
            )
        try:
            item = work_item_provider.get(work_item_id)
        except WorkItemLifecycleError as exc:
            raise TestingWorkflowError(
                f"Unable to verify work-item lifecycle state: {exc}"
            ) from exc
        if item.state != LifecycleState.VERIFICATION:
            raise TestingWorkflowError(
                "Testing requires a work item in verification state; "
                f"got {item.state.value}."
            )
        lifecycle_state = item.state.value
    elif work_item_id:
        raise TestingWorkflowError(
            "work_item_provider is required when work_item_id is supplied."
        )

    return TestingPlan(
        project=str(root),
        manifest=str(manifest_path),
        gates=gates,
        work_item_id=work_item_id,
        lifecycle_state=lifecycle_state,
    )


def run_testing(
    project: str | Path,
    manifest: str | Path = DEFAULT_MANIFEST,
    *,
    work_item_provider: WorkItemProvider | None = None,
    work_item_id: str | None = None,
    evidence_path: str | Path | None = None,
    run_command: CommandRunner | None = None,
) -> dict[str, Any]:
    """Validate and execute the explicit testing contract."""
    plan = prepare_testing(
        project,
        manifest,
        work_item_provider=work_item_provider,
        work_item_id=work_item_id,
    )

    kwargs: dict[str, Any] = {}
    if run_command is not None:
        kwargs["run_command"] = run_command

    try:
        if work_item_provider is None:
            evidence = execute_quality_gates(
                Path(plan.project),
                Path(plan.manifest),
                **kwargs,
            )
            output: dict[str, Any] = {
                "status": evidence.status,
                "project": evidence.project,
                "manifest": evidence.manifest,
                "required_failures": list(evidence.required_failures),
                "gates": [
                    {
                        "id": result.id,
                        "required": result.required,
                        "status": result.status,
                        "exit_code": result.exit_code,
                        "timed_out": result.timed_out,
                        "duration_seconds": result.duration_seconds,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                    for result in evidence.gates
                ],
                "work_item": None,
            }
        else:
            output = run_with_optional_work_item(
                Path(plan.project),
                Path(plan.manifest),
                work_item_provider=work_item_provider,
                work_item_id=plan.work_item_id,
                evidence_path=Path(evidence_path) if evidence_path else None,
                **kwargs,
            )
    except (QualityGateError, WorkItemLifecycleError, OSError, ValueError) as exc:
        raise TestingWorkflowError(str(exc)) from exc

    output["testing_contract"] = {
        "required_gate_ids": list(plan.required_gate_ids),
        "gate_count": len(plan.gates),
    }
    return output


def _github_provider(repository: str, token: str) -> GitHubIssuesProvider:
    return GitHubIssuesProvider(repository, token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and execute the project's explicit testing contract."
    )
    parser.add_argument("project", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Project-local quality-gate manifest.",
    )
    parser.add_argument("--evidence-path", type=Path)
    parser.add_argument("--work-item-id")
    parser.add_argument("--work-item-repository")
    parser.add_argument("--work-item-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if bool(args.work_item_repository) != bool(args.work_item_id):
        print(
            "ERROR: --work-item-repository and --work-item-id must be provided together.",
            file=sys.stderr,
        )
        return 1

    provider = None
    if args.work_item_repository:
        import os

        token = os.environ.get(args.work_item_token_env, "")
        if not token:
            print(
                f"ERROR: GitHub token environment variable {args.work_item_token_env!r} is not set.",
                file=sys.stderr,
            )
            return 1
        provider = _github_provider(args.work_item_repository, token)

    try:
        plan = prepare_testing(
            args.project,
            args.manifest,
            work_item_provider=provider,
            work_item_id=args.work_item_id,
        )
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "status": "validated",
                        "project": plan.project,
                        "manifest": plan.manifest,
                        "required_gate_ids": list(plan.required_gate_ids),
                        "gate_count": len(plan.gates),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        evidence = run_testing(
            args.project,
            args.manifest,
            work_item_provider=provider,
            work_item_id=args.work_item_id,
            evidence_path=args.evidence_path,
        )
    except (TestingWorkflowError, WorkItemLifecycleError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
