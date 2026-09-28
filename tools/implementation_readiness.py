#!/usr/bin/env python3
"""Evaluate whether a classified work item has enough verified evidence for implementation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from architecture_planning import ArchitecturePlanningError, ArchitecturePlan, plan_architecture
from workflow_composition import WorkflowComposition, WorkflowCompositionError, compose_workflow
from requirements_clarification import RequirementsClarificationError, RequirementsReport, clarify_requirements
from work_item_lifecycle import LifecycleState, WorkItemLifecycleError, WorkItemProvider

HTTPS_URL_RE = re.compile(r"^https://[^\s]+$")
FORBIDDEN_CONTROL_RE = re.compile(r"[\x00\r\n]")


class ImplementationReadinessError(RuntimeError):
    """Raised when implementation-readiness evaluation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ReadinessObservation:
    """One deterministic readiness observation."""

    check: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class ImplementationReadiness:
    """Read-only evidence gate for managed implementation."""

    work_item_path: str
    work_item_id: str | None
    work_item_kind: str
    lifecycle_state: str | None
    requirements_status: str
    architecture_required: bool
    version_evidence_ref: str
    observations: tuple[ReadinessObservation, ...]
    blockers: tuple[str, ...]
    composition_steps: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers


def _validate_lifecycle(
    provider: WorkItemProvider | None,
    work_item_id: str | None,
) -> str | None:
    if provider is None and work_item_id is None:
        return None
    if provider is None or work_item_id is None:
        raise ImplementationReadinessError(
            "work-item provider and work-item ID must be provided together."
        )
    try:
        item = provider.get(work_item_id)
    except (WorkItemLifecycleError, ValueError) as exc:
        raise ImplementationReadinessError(
            f"Unable to verify work-item lifecycle state: {exc}"
        ) from exc
    if item.state != LifecycleState.READY:
        raise ImplementationReadinessError(
            "Implementation readiness requires a ready work item; "
            f"observed {item.state.value}."
        )
    return item.state.value


def _validate_version_evidence(project: Path, reference: str | Path) -> tuple[str, str]:
    value = str(reference).strip()
    if not value or FORBIDDEN_CONTROL_RE.search(value):
        raise ImplementationReadinessError(
            "version_evidence_ref must be a non-empty single-line reference."
        )
    if HTTPS_URL_RE.fullmatch(value):
        return "external-reference", value

    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.expanduser().resolve()
    else:
        resolved = (project / candidate).resolve()
    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise ImplementationReadinessError(
            "Local version evidence must remain inside the project root."
        ) from exc
    if not resolved.is_file():
        raise ImplementationReadinessError(
            f"Local version evidence file does not exist: {resolved}"
        )
    try:
        if not resolved.read_text(encoding="utf-8").strip():
            raise ImplementationReadinessError(
                f"Local version evidence file is empty: {resolved}"
            )
    except UnicodeDecodeError as exc:
        raise ImplementationReadinessError(
            f"Local version evidence must be readable UTF-8 text: {resolved}"
        ) from exc
    except OSError as exc:
        raise ImplementationReadinessError(
            f"Unable to read local version evidence file: {resolved}"
        ) from exc
    return "local-file", resolved.relative_to(project).as_posix()


def evaluate_readiness(
    work_item_path: str | Path,
    work_item_kind: str,
    *,
    project_root: str | Path | None = None,
    version_evidence_ref: str | Path,
    architecture_required: bool,
    work_item_provider: WorkItemProvider | None = None,
    work_item_id: str | None = None,
) -> ImplementationReadiness:
    """Evaluate implementation readiness without executing project commands."""
    document = Path(work_item_path).expanduser().resolve()
    if not document.is_file():
        raise ImplementationReadinessError(
            f"Work-item document does not exist: {document}"
        )

    kind = work_item_kind.strip()
    if not kind:
        raise ImplementationReadinessError("work_item_kind must be explicit and non-empty.")

    if work_item_id is not None:
        try:
            markdown = document.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ImplementationReadinessError(
                f"Unable to read canonical work-item document: {document}"
            ) from exc
        identity_match = re.search(
            r"^Work item ID:\s*(\S+)\s*$",
            markdown,
            re.MULTILINE,
        )
        if identity_match is None or identity_match.group(1).lstrip("#") != work_item_id.lstrip("#"):
            raise ImplementationReadinessError(
                "Canonical work-item document does not match the supplied work-item ID."
            )

    project = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else document.parent
    )
    if not project.is_dir():
        raise ImplementationReadinessError(f"Project root does not exist: {project}")
    observations: list[ReadinessObservation] = []
    blockers: list[str] = []

    try:
        requirements: RequirementsReport = clarify_requirements(document)
    except RequirementsClarificationError as exc:
        raise ImplementationReadinessError(str(exc)) from exc

    if requirements.ready:
        observations.append(
            ReadinessObservation(
                "requirements",
                "passed",
                "Requirements clarification has no blocker-level questions.",
            )
        )
    else:
        blockers.append(
            "Requirements clarification still contains blocker-level questions."
        )
        observations.append(
            ReadinessObservation(
                "requirements",
                "blocked",
                f"{len(requirements.questions)} clarification question(s) remain.",
            )
        )

    try:
        composition: WorkflowComposition = compose_workflow(kind)
    except WorkflowCompositionError as exc:
        raise ImplementationReadinessError(str(exc)) from exc

    observations.append(
        ReadinessObservation(
            "workflow-composition",
            "passed",
            f"Explicit work-item kind maps to {len(composition.steps)} registry-validated steps.",
        )
    )

    version_kind, normalized_version_ref = _validate_version_evidence(
        project,
        version_evidence_ref,
    )
    if version_kind == "local-file":
        observations.append(
            ReadinessObservation(
                "version-verification",
                "passed",
                f"Local toolchain evidence exists at {normalized_version_ref}.",
            )
        )
    else:
        observations.append(
            ReadinessObservation(
                "version-verification",
                "blocked",
                f"External toolchain evidence reference is explicit but not independently verified: {normalized_version_ref}.",
            )
        )
        blockers.append(
            "Toolchain evidence must be independently verified locally before managed implementation."
        )

    if architecture_required:
        if not requirements.ready:
            observations.append(
                ReadinessObservation(
                    "architecture",
                    "blocked",
                    "Architecture planning was not executed because requirements clarification is blocked.",
                )
            )
            blockers.append(
                "Architecture planning cannot establish implementation readiness while requirements remain blocked."
            )
        else:
            try:
                architecture: ArchitecturePlan = plan_architecture(
                    document,
                    work_item_reader=work_item_provider,
                    work_item_id=work_item_id if work_item_provider is not None else None,
                )
            except ArchitecturePlanningError as exc:
                raise ImplementationReadinessError(str(exc)) from exc
            if architecture.ready:
                observations.append(
                    ReadinessObservation(
                        "architecture",
                        "passed",
                        "Architecture planning returned no blockers.",
                    )
                )
            else:
                blockers.append(
                    "Architecture planning returned blocker-level information gaps."
                )
                observations.append(
                    ReadinessObservation(
                        "architecture",
                        "blocked",
                        f"{len(architecture.blockers)} architecture blocker(s) remain.",
                    )
                )
    else:
        observations.append(
            ReadinessObservation(
                "architecture",
                "not-required",
                "Architecture impact was explicitly classified as not required for this work item.",
            )
        )

    lifecycle_state = _validate_lifecycle(
        work_item_provider,
        work_item_id if work_item_provider is not None else None,
    )
    if lifecycle_state is not None:
        observations.append(
            ReadinessObservation(
                "lifecycle",
                "passed",
                "Authoritative work item is in ready state.",
            )
        )

    return ImplementationReadiness(
        work_item_path=document.as_posix(),
        work_item_id=work_item_id,
        work_item_kind=kind,
        lifecycle_state=lifecycle_state,
        requirements_status=requirements.status,
        architecture_required=architecture_required,
        version_evidence_ref=normalized_version_ref,
        observations=tuple(observations),
        blockers=tuple(blockers),
        composition_steps=tuple(step.name for step in composition.steps),
    )


def _to_dict(readiness: ImplementationReadiness) -> dict[str, Any]:
    result = asdict(readiness)
    result["ready"] = readiness.ready
    result["summary"] = {
        "blockers": len(readiness.blockers),
        "observations": len(readiness.observations),
        "composition_steps": len(readiness.composition_steps),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate implementation readiness without mutating the project."
    )
    parser.add_argument("work_item", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        help="Explicit target project root used to validate local version evidence.",
    )
    parser.add_argument(
        "--kind",
        required=True,
        help="Explicit work-item kind. It is never inferred.",
    )
    parser.add_argument(
        "--version-evidence-ref",
        required=True,
        help="Explicit toolchain/version evidence: a non-empty project-local UTF-8 file. External URLs remain blocked until independently verified.",
    )
    architecture = parser.add_mutually_exclusive_group(required=True)
    architecture.add_argument(
        "--architecture-required",
        action="store_true",
        help="Require a passing architecture plan.",
    )
    architecture.add_argument(
        "--architecture-not-required",
        action="store_true",
        help="Explicitly classify architecture planning as not required.",
    )
    parser.add_argument("--work-item-id")
    parser.add_argument("--work-item-repository")
    parser.add_argument("--work-item-token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()

    if bool(args.work_item_repository) != bool(args.work_item_id):
        print(
            "ERROR: --work-item-repository and --work-item-id must be provided together.",
            file=sys.stderr,
        )
        return 1

    provider: WorkItemProvider | None = None
    if args.work_item_repository:
        import os

        token = os.environ.get(args.work_item_token_env, "")
        if not token:
            print(
                f"ERROR: GitHub token environment variable {args.work_item_token_env!r} is not set.",
                file=sys.stderr,
            )
            return 1
        from work_item_lifecycle import GitHubIssuesProvider

        provider = GitHubIssuesProvider(args.work_item_repository, token)

    try:
        readiness = evaluate_readiness(
            args.work_item,
            args.kind,
            project_root=args.project_root,
            version_evidence_ref=args.version_evidence_ref,
            architecture_required=args.architecture_required,
            work_item_provider=provider,
            work_item_id=args.work_item_id,
        )
    except (ImplementationReadinessError, WorkItemLifecycleError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(readiness), indent=2, sort_keys=True))
    return 0 if readiness.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
