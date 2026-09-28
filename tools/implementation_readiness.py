#!/usr/bin/env python3
"""Evaluate whether a classified work item has enough verified evidence for implementation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evidence_contract import EvidenceContractError, write_evidence
from evidence_bundle_requirements import (
    EvidenceSetRequirementsError,
    validate_evidence_set,
)

from architecture_planning import ArchitecturePlanningError, ArchitecturePlan, plan_architecture
from workflow_composition import WorkflowComposition, WorkflowCompositionError, compose_workflow
from requirements_clarification import RequirementsClarificationError, RequirementsReport, clarify_requirements
from version_verification import VersionVerificationError, validate_version_evidence
from work_item_lifecycle import LifecycleState, WorkItemLifecycleError, WorkItemProvider


class ImplementationReadinessError(RuntimeError):
    """Raised when implementation-readiness evaluation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class EvidenceSetReadiness:
    """Observed result of an explicitly supplied evidence-set readiness contract."""

    status: str
    bundle_id: str | None
    requirements_ref: str
    requirements_satisfied: int
    requirements_total: int
    detail: str


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
    version_external_verification_pending: bool
    observations: tuple[ReadinessObservation, ...]
    blockers: tuple[str, ...]
    composition_steps: tuple[str, ...]
    evidence_set: "EvidenceSetReadiness | None" = None

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


def _validate_version_evidence(project: Path, reference: str | Path) -> tuple[str, int, bool]:
    value = str(reference).strip()
    if not value:
        raise ImplementationReadinessError(
            "version_evidence_ref must be a non-empty project-local evidence file."
        )
    if value.startswith("http://") or value.startswith("https://"):
        raise ImplementationReadinessError(
            "version_evidence_ref must reference local schema-validated version evidence."
        )

    path = Path(value)
    if path.is_absolute():
        resolved = path.expanduser().resolve()
    else:
        resolved = (project / path).resolve()

    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise ImplementationReadinessError(
            "Version evidence must remain inside the project root."
        ) from exc

    try:
        evidence = validate_version_evidence(project, resolved)
    except VersionVerificationError as exc:
        raise ImplementationReadinessError(
            f"Version evidence validation failed: {exc}"
        ) from exc

    return (
        resolved.relative_to(project).as_posix(),
        len(evidence.claims),
        evidence.external_verification_pending,
    )


def _resolve_local_reference(
    project: Path,
    reference: str | Path,
    label: str,
) -> tuple[Path, str]:
    """Resolve an explicit project-local evidence reference without remote access."""
    value = str(reference).strip()
    if not value:
        raise ImplementationReadinessError(f"{label} must be a non-empty project-local path.")
    if value.startswith("http://") or value.startswith("https://"):
        raise ImplementationReadinessError(f"{label} must reference a local project file.")

    candidate = Path(value).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (project / candidate).resolve()
    try:
        relative = resolved.relative_to(project)
    except ValueError as exc:
        raise ImplementationReadinessError(
            f"{label} must remain inside the project root."
        ) from exc
    if not resolved.is_file():
        raise ImplementationReadinessError(
            f"{label} does not reference an existing file: {resolved}"
        )
    return resolved, relative.as_posix()


def _validate_evidence_set(
    project: Path,
    bundle_reference: str | Path,
    requirements_reference: str | Path,
) -> EvidenceSetReadiness:
    """Validate an explicit evidence-set contract without inferring its requirements."""
    bundle_path, _bundle_ref = _resolve_local_reference(project, bundle_reference, "evidence bundle")
    requirements_path, requirements_ref = _resolve_local_reference(
        project,
        requirements_reference,
        "evidence-set requirements",
    )
    try:
        result = validate_evidence_set(project, bundle_path, requirements_path)
    except EvidenceSetRequirementsError as exc:
        return EvidenceSetReadiness(
            status="blocked",
            bundle_id=None,
            requirements_ref=requirements_ref,
            requirements_satisfied=0,
            requirements_total=0,
            detail=str(exc),
        )
    return EvidenceSetReadiness(
        status=result.status,
        bundle_id=result.bundle_id,
        requirements_ref=requirements_ref,
        requirements_satisfied=result.requirements_satisfied,
        requirements_total=result.requirements_total,
        detail="Explicit evidence-set requirements are satisfied.",
    )


def evaluate_readiness(
    work_item_path: str | Path,
    work_item_kind: str,
    *,
    project_root: str | Path | None = None,
    version_evidence_ref: str | Path,
    architecture_required: bool,
    work_item_provider: WorkItemProvider | None = None,
    work_item_id: str | None = None,
    evidence_bundle_ref: str | Path | None = None,
    evidence_set_requirements_ref: str | Path | None = None,
) -> ImplementationReadiness:
    """Evaluate implementation readiness without executing project commands."""
    document = Path(work_item_path).expanduser().resolve()
    if not document.is_file():
        raise ImplementationReadinessError(
            f"Work-item document does not exist: {document}"
        )

    if (evidence_bundle_ref is None) != (evidence_set_requirements_ref is None):
        raise ImplementationReadinessError(
            "evidence_bundle_ref and evidence_set_requirements_ref must be provided together."
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

    (
        normalized_version_ref,
        version_claim_count,
        version_external_verification_pending,
    ) = _validate_version_evidence(
        project,
        version_evidence_ref,
    )
    observations.append(
        ReadinessObservation(
            "version-verification",
            "pending" if version_external_verification_pending else "passed",
            (
                f"Validated version evidence contains {version_claim_count} source-pinned claim(s) at "
                f"{normalized_version_ref}; external compatibility verification remains pending."
                if version_external_verification_pending
                else f"Validated version evidence contains {version_claim_count} source-pinned claim(s) at {normalized_version_ref}."
            ),
        )
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

    evidence_set: EvidenceSetReadiness | None = None
    if evidence_bundle_ref is not None and evidence_set_requirements_ref is not None:
        evidence_set = _validate_evidence_set(
            project,
            evidence_bundle_ref,
            evidence_set_requirements_ref,
        )
        if evidence_set.status == "verified":
            observations.append(
                ReadinessObservation(
                    "evidence-set",
                    "passed",
                    (
                        "Explicit evidence-set requirements are satisfied: "
                        f"{evidence_set.requirements_satisfied}/"
                        f"{evidence_set.requirements_total} requirement(s) in bundle "
                        f"{evidence_set.bundle_id}."
                    ),
                )
            )
        else:
            observations.append(
                ReadinessObservation("evidence-set", "blocked", evidence_set.detail)
            )
            blockers.append("Explicit evidence-set requirements are not satisfied.")

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
        version_external_verification_pending=version_external_verification_pending,
        observations=tuple(observations),
        blockers=tuple(blockers),
        composition_steps=tuple(step.name for step in composition.steps),
        evidence_set=evidence_set,
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
        help="Project-local version-evidence JSON produced and validated by tools/version_verification.py.",
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Optional canonical implementation-readiness evidence output path.",
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
    parser.add_argument(
        "--evidence-bundle",
        type=Path,
        help="Optional project-local canonical evidence bundle required by the readiness gate.",
    )
    parser.add_argument(
        "--evidence-set-requirements",
        type=Path,
        help="Optional project-local explicit evidence-set requirements contract.",
    )
    parser.add_argument("--work-item-repository")
    parser.add_argument("--work-item-token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()

    if (args.evidence_bundle is None) != (args.evidence_set_requirements is None):
        print(
            "ERROR: --evidence-bundle and --evidence-set-requirements must be provided together.",
            file=sys.stderr,
        )
        return 1

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
        observed_at = datetime.now(timezone.utc)
        readiness = evaluate_readiness(
            args.work_item,
            args.kind,
            project_root=args.project_root,
            version_evidence_ref=args.version_evidence_ref,
            architecture_required=args.architecture_required,
            work_item_provider=provider,
            work_item_id=args.work_item_id,
            evidence_bundle_ref=args.evidence_bundle,
            evidence_set_requirements_ref=args.evidence_set_requirements,
        )

        if args.evidence_output is not None:
            from evidence_adapters import implementation_readiness_evidence

            output_path = args.evidence_output.expanduser()
            project_root = (
                args.project_root.expanduser().resolve()
                if args.project_root is not None
                else args.work_item.expanduser().resolve().parent
            )
            if not output_path.is_absolute():
                output_path = project_root / output_path
            output_path = output_path.resolve()

            evidence_bundle_path, _ = (
                _resolve_local_reference(project_root, args.evidence_bundle, "evidence bundle")
                if args.evidence_bundle is not None
                else (None, None)
            )
            requirements_path, _ = (
                _resolve_local_reference(
                    project_root,
                    args.evidence_set_requirements,
                    "evidence-set requirements",
                )
                if args.evidence_set_requirements is not None
                else (None, None)
            )

            work_item_path = args.work_item.expanduser().resolve()
            version_evidence_path = Path(args.version_evidence_ref).expanduser()
            if not version_evidence_path.is_absolute():
                version_evidence_path = project_root / version_evidence_path
            version_evidence_path = version_evidence_path.resolve()

            protected_inputs = {work_item_path, version_evidence_path}
            if evidence_bundle_path is not None:
                protected_inputs.add(evidence_bundle_path)
            if requirements_path is not None:
                protected_inputs.add(requirements_path)
            if output_path in protected_inputs:
                raise ImplementationReadinessError(
                    "Canonical evidence output must not overwrite any readiness input artifact."
                )

            write_evidence(
                implementation_readiness_evidence(
                    readiness,
                    observed_at=observed_at,
                ),
                output_path,
            )
    except (ImplementationReadinessError, WorkItemLifecycleError, EvidenceContractError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(readiness), indent=2, sort_keys=True))
    return 0 if readiness.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
