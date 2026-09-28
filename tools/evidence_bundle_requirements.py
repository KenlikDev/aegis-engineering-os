#!/usr/bin/env python3
"""Validate canonical evidence bundles against explicit evidence-set requirements."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from evidence_bundle import EvidenceBundle, EvidenceBundleError, read_and_validate_evidence_bundle
from evidence_contract import (
    ALLOWED_STATUSES,
    KIND_RE,
    EvidenceContractError,
    EvidenceRecord,
    SHA256_RE,
    read_and_validate_evidence,
)


SCHEMA_VERSION = 1
REQUIREMENT_KEYS = frozenset({"kind", "status", "subject", "source"})
REQUIREMENTS_KEYS = frozenset({"schema_version", "requirements", "allow_extra_members"})
MAX_REQUIREMENTS = 64
REQUIREMENT_SET_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SELECTOR_LENGTH = 4096


class EvidenceSetRequirementsError(RuntimeError):
    """Raised when an evidence-set requirements contract cannot be satisfied safely."""


@dataclass(frozen=True, slots=True)
class EvidenceSelector:
    """Explicit selector describing one required evidence member."""

    kind: str
    status: str | None = None
    subject: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceSetRequirements:
    """Machine-readable evidence membership requirements."""

    schema_version: int
    requirements: tuple[EvidenceSelector, ...]
    allow_extra_members: bool


@dataclass(frozen=True, slots=True)
class EvidenceSetValidation:
    """Deterministic validation result for one bundle against one contract."""

    status: str
    bundle_id: str
    requirements_satisfied: int
    requirements_total: int
    matched_members: tuple[Mapping[str, Any], ...]
    extra_members: tuple[Mapping[str, Any], ...]


def _clean_selector_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise EvidenceSetRequirementsError(f"{field} must be a string.")
    if not value or value != value.strip():
        raise EvidenceSetRequirementsError(
            f"{field} must be a non-empty trimmed string."
        )
    if len(value) > MAX_SELECTOR_LENGTH or any(
        char in value for char in "\x00\r\n"
    ):
        raise EvidenceSetRequirementsError(
            f"{field} contains invalid or oversized text."
        )
    return value


def _parse_requirement(value: object, index: int) -> EvidenceSelector:
    if not isinstance(value, Mapping) or set(value) != REQUIREMENT_KEYS:
        raise EvidenceSetRequirementsError(
            f"Evidence requirement {index} has an invalid schema."
        )

    kind = value.get("kind")
    if not isinstance(kind, str) or not KIND_RE.fullmatch(kind):
        raise EvidenceSetRequirementsError(
            f"Evidence requirement {index} has an invalid kind."
        )

    status = value.get("status")
    if status is not None:
        if not isinstance(status, str) or status not in ALLOWED_STATUSES:
            raise EvidenceSetRequirementsError(
                f"Evidence requirement {index} has an invalid status."
            )

    subject = value.get("subject")
    if subject is not None:
        subject = _clean_selector_text(subject, f"Evidence requirement {index} subject")

    source = value.get("source")
    if source is not None:
        source = _clean_selector_text(source, f"Evidence requirement {index} source")

    return EvidenceSelector(
        kind=kind,
        status=status,
        subject=subject,
        source=source,
    )


def load_requirements(path: str | Path) -> EvidenceSetRequirements:
    """Read and validate an explicit evidence-set requirements document."""
    requirements_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(
            requirements_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constants,
        )
    except EvidenceSetRequirementsError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceSetRequirementsError(
            f"Unable to read evidence-set requirements: {requirements_path}"
        ) from exc

    if not isinstance(payload, Mapping) or set(payload) != REQUIREMENTS_KEYS:
        raise EvidenceSetRequirementsError(
            "Evidence-set requirements contain an invalid top-level schema."
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceSetRequirementsError(
            f"Unsupported evidence-set requirements schema version: "
            f"{payload.get('schema_version')!r}."
        )

    raw_requirements = payload.get("requirements")
    if (
        not isinstance(raw_requirements, list)
        or not raw_requirements
        or len(raw_requirements) > MAX_REQUIREMENTS
    ):
        raise EvidenceSetRequirementsError(
            f"requirements must contain between 1 and {MAX_REQUIREMENTS} selectors."
        )

    parsed = tuple(
        _parse_requirement(item, index)
        for index, item in enumerate(raw_requirements)
    )
    if len(set(parsed)) != len(parsed):
        raise EvidenceSetRequirementsError(
            "Evidence-set requirements must not contain duplicate selectors."
        )

    allow_extra_members = payload.get("allow_extra_members")
    if not isinstance(allow_extra_members, bool):
        raise EvidenceSetRequirementsError("allow_extra_members must be a boolean.")

    return EvidenceSetRequirements(
        schema_version=SCHEMA_VERSION,
        requirements=parsed,
        allow_extra_members=allow_extra_members,
    )


def _reject_constants(value: str) -> None:
    raise EvidenceSetRequirementsError(f"JSON constant {value!r} is not allowed.")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceSetRequirementsError(
                f"Duplicate JSON key: {key!r}."
            )
        result[key] = value
    return result


def _matches(selector: EvidenceSelector, evidence: EvidenceRecord) -> bool:
    return (
        evidence.kind == selector.kind
        and (selector.status is None or evidence.status == selector.status)
        and (selector.subject is None or evidence.subject == selector.subject)
        and (selector.source is None or evidence.source == selector.source)
    )


def _load_bundle_members(
    project: str | Path,
    bundle: EvidenceBundle,
) -> list[tuple[Any, EvidenceRecord]]:
    root = Path(project).expanduser().resolve()
    members: list[tuple[Any, EvidenceRecord]] = []
    for member in bundle.members:
        path = (root / member.path).resolve()
        try:
            evidence = read_and_validate_evidence(path)
        except (EvidenceContractError, OSError) as exc:
            raise EvidenceSetRequirementsError(
                f"Evidence member {member.path!r} failed canonical validation: {exc}"
            ) from exc
        if evidence.evidence_id != member.evidence_id:
            raise EvidenceSetRequirementsError(
                f"Evidence member {member.path!r} changed identity after bundle validation."
            )
        members.append((member, evidence))
    return members


def validate_evidence_set(
    project: str | Path,
    bundle_path: str | Path,
    requirements_path: str | Path,
) -> EvidenceSetValidation:
    """Validate one canonical evidence bundle against explicit selectors."""
    try:
        bundle = read_and_validate_evidence_bundle(project, bundle_path)
    except EvidenceBundleError as exc:
        raise EvidenceSetRequirementsError(str(exc)) from exc

    requirements = load_requirements(requirements_path)
    members = _load_bundle_members(project, bundle)

    used_member_ids: set[str] = set()
    matched: list[Mapping[str, Any]] = []
    missing: list[Mapping[str, Any]] = []

    for index, selector in enumerate(requirements.requirements):
        match = next(
            (
                (member, evidence)
                for member, evidence in members
                if member.evidence_id not in used_member_ids
                and _matches(selector, evidence)
            ),
            None,
        )
        selector_output = {
            "index": index,
            "kind": selector.kind,
            "status": selector.status,
            "subject": selector.subject,
            "source": selector.source,
        }
        if match is None:
            missing.append(selector_output)
            continue

        member, evidence = match
        used_member_ids.add(member.evidence_id)
        matched.append(
            {
                **selector_output,
                "evidence_id": evidence.evidence_id,
                "path": member.path,
            }
        )

    extras = [
        {
            "evidence_id": member.evidence_id,
            "path": member.path,
            "kind": evidence.kind,
            "status": evidence.status,
            "subject": evidence.subject,
            "source": evidence.source,
        }
        for member, evidence in members
        if member.evidence_id not in used_member_ids
    ]

    if missing:
        raise EvidenceSetRequirementsError(
            "Evidence-set requirements are not satisfied: "
            + json.dumps(missing, ensure_ascii=False, sort_keys=True)
        )
    if not requirements.allow_extra_members and extras:
        raise EvidenceSetRequirementsError(
            "Evidence bundle contains extra members but the requirements contract "
            "sets allow_extra_members=false: "
            + json.dumps(extras, ensure_ascii=False, sort_keys=True)
        )

    return EvidenceSetValidation(
        status="verified",
        bundle_id=bundle.bundle_id,
        requirements_satisfied=len(matched),
        requirements_total=len(requirements.requirements),
        matched_members=tuple(matched),
        extra_members=tuple(extras),
    )


def _to_dict(result: EvidenceSetValidation) -> dict[str, Any]:
    return {
        "status": result.status,
        "bundle_id": result.bundle_id,
        "requirements_satisfied": result.requirements_satisfied,
        "requirements_total": result.requirements_total,
        "matched_members": list(result.matched_members),
        "extra_members": list(result.extra_members),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a canonical evidence bundle against explicit requirements."
    )
    parser.add_argument("project", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("requirements", type=Path)
    args = parser.parse_args()

    try:
        result = validate_evidence_set(
            args.project,
            args.bundle,
            args.requirements,
        )
    except EvidenceSetRequirementsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
