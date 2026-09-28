#!/usr/bin/env python3
"""Produce a deterministic, read-only architecture plan from a ready work item."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from evidence_contract import EvidenceContractError, write_evidence

from requirements_clarification import RequirementsClarificationError, clarify_requirements
from work_item_lifecycle import LifecycleState, WorkItemLifecycleError, WorkItemProvider


class ArchitecturePlanningError(RuntimeError):
    """Raised when an architecture plan cannot be produced safely."""


@dataclass(frozen=True, slots=True)
class ArchitectureEvidence:
    """One explicit fact copied from the canonical work item."""

    evidence_id: str
    source: str
    value: str


@dataclass(frozen=True, slots=True)
class ArchitectureDeduction:
    """One deterministic technical deduction derived from explicit evidence."""

    deduction_id: str
    basis: str
    conclusion: str


@dataclass(frozen=True, slots=True)
class ArchitectureQuestion:
    """One unresolved user-owned or architecture-critical question."""

    question_id: str
    ownership: str
    question: str
    basis: str


@dataclass(frozen=True, slots=True)
class ArchitecturePlan:
    """Structured read-only architecture planning result."""

    path: str
    work_item_id: str | None
    lifecycle_state: str | None
    status: str
    requirements_status: str
    evidence: tuple[ArchitectureEvidence, ...]
    deductions: tuple[ArchitectureDeduction, ...]
    constraints: tuple[str, ...]
    boundaries: tuple[str, ...]
    affected_components: tuple[str, ...]
    adr_needs: tuple[str, ...]
    non_goals: tuple[str, ...]
    user_owned_decisions: tuple[ArchitectureQuestion, ...]
    blockers: tuple[ArchitectureQuestion, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


class ReadyWorkItemReader(Protocol):
    """Provider-neutral contract for checking lifecycle readiness."""

    def get(self, work_item_id: str) -> Any:
        ...


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _sections(markdown: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, re.MULTILINE))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = _normalize(match.group(1)).lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        result[heading] = markdown[match.end() : end].strip()
    return result


def _subsections(section_text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", section_text, re.MULTILINE))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = _normalize(match.group(1)).lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        result[heading] = section_text[match.end() : end].strip()
    return result


def _meaningful_lines(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for raw_line in text.splitlines():
        line = _normalize(raw_line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\[[ xX]\]\s+", "", line)
        if not line or line.startswith("#"):
            continue
        if line in {"...", "What outcome is required?", "TBD", "TODO"}:
            continue
        values.append(line)
    return tuple(values)


def _explicit_prefixed_lines(text: str, prefixes: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for line in _meaningful_lines(text):
        lowered = line.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix.lower()):
                value = line[len(prefix) :].strip(" :")
                if value:
                    values.append(value)
                break
    return tuple(values)


def _deduplicate(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize(value)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return tuple(result)


def _architecture_evidence(sections: Mapping[str, str]) -> tuple[ArchitectureEvidence, ...]:
    evidence: list[ArchitectureEvidence] = []
    for source, section_name in (
        ("Technical notes", "technical notes"),
        ("Dependencies", "dependencies"),
        ("Risks", "risks"),
    ):
        for index, value in enumerate(_meaningful_lines(sections.get(section_name, "")), start=1):
            evidence.append(
                ArchitectureEvidence(
                    f"{section_name.replace(' ', '-')}.{index}",
                    source,
                    value,
                )
            )
    return tuple(evidence)


def _component_references(sections: Mapping[str, str]) -> tuple[str, ...]:
    """Extract only explicit component/path references; never invent component names."""
    values: list[str] = []
    notes = sections.get("technical notes", "")
    values.extend(
        _explicit_prefixed_lines(
            notes,
            ("affected component", "component", "module", "service"),
        )
    )
    backtick = chr(96)
    token_pattern = re.escape(backtick) + r"([^" + re.escape(backtick) + r"\n]+)" + re.escape(backtick)
    for text in (sections.get("dependencies", ""), notes):
        for match in re.finditer(token_pattern, text):
            token = _normalize(match.group(1))
            if "/" in token or "." in token or "::" in token:
                values.append(token)
    return _deduplicate(values)


def _build_deductions(
    evidence: tuple[ArchitectureEvidence, ...],
    components: tuple[str, ...],
) -> tuple[ArchitectureDeduction, ...]:
    deductions: list[ArchitectureDeduction] = []
    if components:
        deductions.append(
            ArchitectureDeduction(
                "boundaries.explicit-components",
                "Explicit component/module/service references were found in technical notes or dependencies.",
                "Architecture planning must preserve those references as affected-component boundaries and must not expand them without new evidence.",
            )
        )
    if any(item.source == "Dependencies" for item in evidence):
        deductions.append(
            ArchitectureDeduction(
                "constraints.dependencies",
                "The work item explicitly records one or more dependencies.",
                "Dependency direction and compatibility must be verified before implementation changes are selected.",
            )
        )
    if any(item.source == "Risks" for item in evidence):
        deductions.append(
            ArchitectureDeduction(
                "adr.risk-review",
                "The work item explicitly records risk information.",
                "Any architecture decision that materially changes a recorded risk should be captured in an ADR or equivalent decision record.",
            )
        )
    return tuple(deductions)


def _validate_lifecycle(
    reader: ReadyWorkItemReader | None,
    work_item_id: str | None,
) -> tuple[str | None, str | None]:
    if reader is None and work_item_id is None:
        return None, None
    if reader is None or work_item_id is None:
        raise ArchitecturePlanningError(
            "Lifecycle repository and work-item ID must be provided together."
        )
    try:
        item = reader.get(work_item_id)
    except (WorkItemLifecycleError, ValueError) as exc:
        raise ArchitecturePlanningError(
            f"Unable to verify work-item lifecycle state: {exc}"
        ) from exc
    state = getattr(item, "state", None)
    state_value = state.value if isinstance(state, LifecycleState) else str(state)
    if state != LifecycleState.READY:
        raise ArchitecturePlanningError(
            f"Architecture planning requires a ready work item; observed {state_value}."
        )
    return work_item_id, state_value


def plan_architecture(
    path: str | Path,
    *,
    work_item_reader: ReadyWorkItemReader | None = None,
    work_item_id: str | None = None,
) -> ArchitecturePlan:
    """Build a deterministic architecture plan without mutating any input."""
    document = Path(path).expanduser().resolve()
    if not document.is_file():
        raise ArchitecturePlanningError(f"Work-item document does not exist: {document}")
    try:
        markdown = document.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ArchitecturePlanningError(
            f"Unable to read work-item document: {document}"
        ) from exc

    try:
        requirements = clarify_requirements(document)
    except RequirementsClarificationError as exc:
        raise ArchitecturePlanningError(str(exc)) from exc

    lifecycle_id, lifecycle_state = _validate_lifecycle(work_item_reader, work_item_id)
    sections = _sections(markdown)
    scope_parts = _subsections(sections.get("scope", ""))
    evidence = _architecture_evidence(sections)
    components = _component_references(sections)
    deductions = _build_deductions(evidence, components)

    constraints = _deduplicate(
        list(_meaningful_lines(sections.get("technical notes", "")))
        + list(_meaningful_lines(sections.get("dependencies", "")))
    )
    boundaries = _deduplicate(
        list(_meaningful_lines(scope_parts.get("in scope", "")))
        + list(_meaningful_lines(scope_parts.get("out of scope", "")))
    )
    non_goals = _deduplicate(_meaningful_lines(scope_parts.get("out of scope", "")))

    adr_needs: list[str] = []
    if len(components) > 1:
        adr_needs.append(
            "Assess whether the cross-component boundary is a durable architectural decision requiring an ADR."
        )
    if any(
        "alternative" in item.value.lower() or "trade-off" in item.value.lower()
        for item in evidence
    ):
        adr_needs.append(
            "Record the documented alternative or trade-off in an ADR before implementation if it changes durable architecture."
        )
    if any(item.source == "Risks" for item in evidence):
        adr_needs.append(
            "Review architecture decisions against the recorded risks and document any material risk trade-off."
        )

    user_owned: list[ArchitectureQuestion] = []
    blockers: list[ArchitectureQuestion] = []
    for question in requirements.questions:
        if question.severity != "blocker":
            continue
        item = ArchitectureQuestion(
            question.question_id,
            "user-or-authoritative-source",
            question.question,
            question.evidence,
        )
        user_owned.append(item)
        blockers.append(item)

    technical_notes = _meaningful_lines(sections.get("technical notes", ""))
    if not technical_notes:
        blockers.append(
            ArchitectureQuestion(
                "architecture.technical-notes",
                "engineering-evidence",
                "What existing technical constraints or affected components must the architecture preserve?",
                "Technical notes contain no explicit architecture-relevant evidence.",
            )
        )
    if not components:
        blockers.append(
            ArchitectureQuestion(
                "architecture.affected-components",
                "engineering-evidence",
                "Which existing components, modules, services, or explicit repository paths are affected?",
                "No explicit affected component reference was found; Aegis will not invent one.",
            )
        )

    return ArchitecturePlan(
        path=document.as_posix(),
        work_item_id=lifecycle_id,
        lifecycle_state=lifecycle_state,
        status="blocked" if blockers else "ready",
        requirements_status=requirements.status,
        evidence=evidence,
        deductions=deductions,
        constraints=constraints,
        boundaries=boundaries,
        affected_components=components,
        adr_needs=_deduplicate(adr_needs),
        non_goals=non_goals,
        user_owned_decisions=tuple(user_owned),
        blockers=tuple(blockers),
    )


def _to_dict(plan: ArchitecturePlan) -> dict[str, Any]:
    result = asdict(plan)
    result["ready"] = plan.ready
    result["summary"] = {
        "blockers": len(plan.blockers),
        "user_owned_decisions": len(plan.user_owned_decisions),
        "evidence": len(plan.evidence),
        "deductions": len(plan.deductions),
        "adr_needs": len(plan.adr_needs),
    }
    return result


def _github_reader(repository: str, token: str) -> WorkItemProvider:
    from work_item_lifecycle import GitHubIssuesProvider

    return GitHubIssuesProvider(repository, token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic architecture plan from a ready work item."
    )
    parser.add_argument("work_item")
    parser.add_argument(
        "--work-item-repository",
        help="GitHub OWNER/REPO used to verify lifecycle readiness.",
    )
    parser.add_argument(
        "--work-item-id",
        help="GitHub issue number for the ready-state precondition.",
    )
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    parser.add_argument(
        "--canonical-evidence-output",
        type=Path,
        help="Optional canonical evidence-provenance output path.",
    )
    args = parser.parse_args()

    if bool(args.work_item_repository) != bool(args.work_item_id):
        print(
            "ERROR: --work-item-repository and --work-item-id must be provided together.",
            file=sys.stderr,
        )
        return 1

    reader = None
    if args.work_item_repository:
        token = os.environ.get(args.github_token_env, "")
        if not token:
            print(
                f"ERROR: GitHub token environment variable {args.github_token_env!r} is not set.",
                file=sys.stderr,
            )
            return 1
        try:
            reader = _github_reader(args.work_item_repository, token)
        except WorkItemLifecycleError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    try:
        plan = plan_architecture(
            args.work_item,
            work_item_reader=reader,
            work_item_id=args.work_item_id,
        )
        if args.canonical_evidence_output is not None:
            from evidence_adapters import architecture_planning_evidence

            output_path = args.canonical_evidence_output.expanduser()
            if not output_path.is_absolute():
                output_path = Path(args.work_item).expanduser().resolve().parent / output_path
            output_path = output_path.resolve()
            work_item_path = Path(args.work_item).expanduser().resolve()
            if output_path == work_item_path:
                raise ArchitecturePlanningError(
                    "Canonical evidence output must not overwrite the work-item document."
                )
            write_evidence(
                architecture_planning_evidence(
                    plan,
                    observed_at=datetime.now(timezone.utc),
                ),
                output_path,
            )
    except (ArchitecturePlanningError, EvidenceContractError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(plan), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if plan.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
