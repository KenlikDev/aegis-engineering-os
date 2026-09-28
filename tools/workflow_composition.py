#!/usr/bin/env python3
"""Build a deterministic workflow composition for an explicitly classified work item."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[1] / "skills" / "registry.json"
)
SUPPORTED_KINDS = frozenset({"feature", "bug-fix", "refactoring", "ci-remediation"})


class WorkflowCompositionError(RuntimeError):
    """Raised when a workflow composition cannot be produced safely."""


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One ordered workflow capability."""

    name: str
    kind: str
    required: bool
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowComposition:
    """Deterministic workflow composition for one explicit work-item kind."""

    work_item_kind: str
    steps: tuple[WorkflowStep, ...]

    @property
    def required_steps(self) -> tuple[WorkflowStep, ...]:
        return tuple(step for step in self.steps if step.required)


def _step(
    name: str,
    kind: str = "workflow",
    *,
    required: bool = True,
    condition: str | None = None,
) -> WorkflowStep:
    return WorkflowStep(name=name, kind=kind, required=required, condition=condition)


COMMON_PREFIX = (
    _step("work-item-lifecycle"),
    _step("requirements-clarification"),
    _step("project-discovery"),
    _step("version-verification", "skill"),
    _step(
        "architecture-planning",
        required=False,
        condition=(
            "Run when architecture-relevant constraints, affected components, "
            "cross-component boundaries, or durable structural changes are present."
        ),
    ),
)

COMPOSITIONS: Mapping[str, tuple[WorkflowStep, ...]] = {
    "feature": COMMON_PREFIX
    + (
        _step("feature-implementation"),
        _step("testing"),
        _step(
            "security-review",
            required=False,
            condition="Run when the change reaches the security-review applicability boundary.",
        ),
        _step("code-review"),
        _step(
            "integration-delivery",
            required=False,
            condition="Run when implementation changes are ready for controlled integration.",
        ),
    ),
    "bug-fix": COMMON_PREFIX
    + (
        _step("bug-fix"),
        _step("testing"),
        _step(
            "security-review",
            required=False,
            condition="Run when the fix reaches the security-review applicability boundary.",
        ),
        _step("code-review"),
        _step(
            "integration-delivery",
            required=False,
            condition="Run when implementation changes are ready for controlled integration.",
        ),
    ),
    "refactoring": COMMON_PREFIX
    + (
        _step("refactoring"),
        _step("testing"),
        _step(
            "security-review",
            required=False,
            condition="Run when the refactor changes a security or privacy boundary or otherwise requires security review.",
        ),
        _step("code-review"),
        _step(
            "integration-delivery",
            required=False,
            condition="Run when implementation changes are ready for controlled integration.",
        ),
    ),
    "ci-remediation": (
        _step("work-item-lifecycle"),
        _step("requirements-clarification"),
        _step("project-discovery"),
        _step("ci-remediation"),
        _step("testing"),
        _step(
            "security-review",
            required=False,
            condition="Run when the CI change reaches the security-review applicability boundary.",
        ),
        _step("code-review"),
        _step(
            "integration-delivery",
            required=False,
            condition="Run when implementation changes are ready for controlled integration.",
        ),
    ),
}


def _load_registry(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowCompositionError(
            f"Unable to read skill registry {path}: {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        raise WorkflowCompositionError("Skill registry must contain a skills list.")

    names: set[str] = set()
    for entry in data["skills"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise WorkflowCompositionError("Every skill registry entry must contain a name.")
        name = entry["name"]
        if name in names:
            raise WorkflowCompositionError(f"Duplicate skill in registry: {name}")
        names.add(name)
    return names


def compose_workflow(
    work_item_kind: str,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
) -> WorkflowComposition:
    """Return the explicit workflow sequence for a supported work-item kind."""
    kind = work_item_kind.strip()
    if kind not in SUPPORTED_KINDS:
        supported = ", ".join(sorted(SUPPORTED_KINDS))
        raise WorkflowCompositionError(
            f"work_item_kind must be one of: {supported}. "
            "Aegis does not infer a kind from free-form task text."
        )

    steps = COMPOSITIONS[kind]
    registry_names = _load_registry(Path(registry_path).expanduser().resolve())
    missing = [step.name for step in steps if step.name not in registry_names]
    if missing:
        raise WorkflowCompositionError(
            "Workflow composition references unregistered skills: "
            + ", ".join(missing)
        )

    if len({step.name for step in steps}) != len(steps):
        raise WorkflowCompositionError(
            f"Workflow composition for {kind!r} contains duplicate steps."
        )

    return WorkflowComposition(work_item_kind=kind, steps=steps)


def _to_dict(composition: WorkflowComposition) -> dict[str, Any]:
    result = asdict(composition)
    result["required_steps"] = [
        step.name for step in composition.required_steps
    ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic workflow composition for an explicit work-item kind."
    )
    parser.add_argument(
        "--kind",
        required=True,
        help="Explicit work-item kind: feature, bug-fix, refactoring, or ci-remediation.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Aegis skill registry used to validate referenced capabilities.",
    )
    args = parser.parse_args()

    try:
        composition = compose_workflow(args.kind, registry_path=args.registry)
    except WorkflowCompositionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(composition), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
