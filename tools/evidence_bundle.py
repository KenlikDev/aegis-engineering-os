#!/usr/bin/env python3
"""Compose and validate deterministic bundles of canonical Aegis evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from evidence_contract import (
    EvidenceContractError,
    SHA256_RE,
    load_json_object,
    read_and_validate_evidence,
)


SCHEMA_VERSION = 1
MAX_PURPOSE_LENGTH = 1024
MAX_MEMBERS = 64
BUNDLE_ID_KEY = "bundle_id"
BUNDLE_KEYS = frozenset({"schema_version", BUNDLE_ID_KEY, "purpose", "members"})
MEMBER_KEYS = frozenset({"evidence_id", "path"})
RELATIVE_PATH_RE = re.compile(r"^[^\\\x00\r\n]+$")


class EvidenceBundleError(RuntimeError):
    """Raised when an evidence bundle cannot be safely created or validated."""


@dataclass(frozen=True, slots=True)
class EvidenceBundleMember:
    """One canonical evidence artifact referenced by a bundle."""

    evidence_id: str
    path: str


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Deterministic collection of validated canonical evidence artifacts."""

    schema_version: int
    bundle_id: str
    purpose: str
    members: tuple[EvidenceBundleMember, ...]


def _clean_purpose(value: object) -> str:
    if not isinstance(value, str):
        raise EvidenceBundleError("purpose must be a string.")
    if not value or value != value.strip():
        raise EvidenceBundleError("purpose must be a non-empty trimmed string.")
    if len(value) > MAX_PURPOSE_LENGTH or any(char in value for char in "\x00\r\n"):
        raise EvidenceBundleError("purpose contains invalid or oversized text.")
    return value


def _relative_member_path(root: Path, raw_path: str | Path) -> tuple[Path, str]:
    value = str(raw_path)
    if not RELATIVE_PATH_RE.fullmatch(value):
        raise EvidenceBundleError("Evidence member path contains invalid characters.")
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        raise EvidenceBundleError("Evidence member paths must be project-relative.")

    resolved = (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise EvidenceBundleError(
            "Evidence member path must remain inside the project root."
        ) from exc

    if not resolved.is_file():
        raise EvidenceBundleError(f"Evidence member does not exist: {resolved}")

    relative_text = PurePosixPath(relative.as_posix()).as_posix()
    if relative_text in {"", "."}:
        raise EvidenceBundleError("Evidence member path must reference a file.")
    return resolved, relative_text


def _canonical_payload(bundle: Mapping[str, Any]) -> bytes:
    payload = {
        key: value
        for key, value in bundle.items()
        if key != BUNDLE_ID_KEY
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _bundle_digest(bundle: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(bundle)).hexdigest()


def _validate_members(
    root: Path,
    raw_members: object,
) -> tuple[EvidenceBundleMember, ...]:
    if not isinstance(raw_members, list) or not raw_members:
        raise EvidenceBundleError("Evidence bundle must contain at least one member.")
    if len(raw_members) > MAX_MEMBERS:
        raise EvidenceBundleError("Evidence bundle contains too many members.")

    parsed: list[EvidenceBundleMember] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()

    for index, raw_member in enumerate(raw_members):
        if not isinstance(raw_member, Mapping) or set(raw_member) != MEMBER_KEYS:
            raise EvidenceBundleError(
                f"Evidence bundle member {index} has an invalid schema."
            )
        evidence_id = raw_member.get("evidence_id")
        path_value = raw_member.get("path")
        if (
            not isinstance(evidence_id, str)
            or not SHA256_RE.fullmatch(evidence_id)
        ):
            raise EvidenceBundleError(
                f"Evidence bundle member {index} has an invalid evidence_id."
            )
        if not isinstance(path_value, str):
            raise EvidenceBundleError(
                f"Evidence bundle member {index} path must be a string."
            )

        resolved, relative_path = _relative_member_path(root, path_value)
        try:
            evidence = read_and_validate_evidence(resolved)
        except EvidenceContractError as exc:
            raise EvidenceBundleError(
                f"Evidence member {relative_path!r} is invalid: {exc}"
            ) from exc

        if evidence.evidence_id != evidence_id:
            raise EvidenceBundleError(
                f"Evidence ID mismatch for {relative_path!r}: "
                f"recorded {evidence_id}, observed {evidence.evidence_id}."
            )
        if evidence_id in seen_ids:
            raise EvidenceBundleError(
                f"Duplicate evidence ID in bundle: {evidence_id}."
            )
        if relative_path in seen_paths:
            raise EvidenceBundleError(
                f"Duplicate evidence path in bundle: {relative_path}."
            )

        seen_ids.add(evidence_id)
        seen_paths.add(relative_path)
        parsed.append(
            EvidenceBundleMember(
                evidence_id=evidence_id,
                path=relative_path,
            )
        )

    ordered = tuple(sorted(parsed, key=lambda member: (member.evidence_id, member.path)))
    if tuple(parsed) != ordered:
        raise EvidenceBundleError(
            "Evidence bundle members must be sorted by evidence_id and path."
        )
    return ordered


def _payload_from_bundle(bundle: EvidenceBundle) -> dict[str, Any]:
    return {
        "schema_version": bundle.schema_version,
        "bundle_id": bundle.bundle_id,
        "purpose": bundle.purpose,
        "members": [
            {
                "evidence_id": member.evidence_id,
                "path": member.path,
            }
            for member in bundle.members
        ],
    }


def build_evidence_bundle(
    project: str | Path,
    purpose: str,
    evidence_paths: Sequence[str | Path],
) -> EvidenceBundle:
    """Validate canonical evidence members and build a deterministic bundle."""
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise EvidenceBundleError(f"Project directory does not exist: {root}")
    clean_purpose = _clean_purpose(purpose)

    if not evidence_paths:
        raise EvidenceBundleError("At least one evidence member is required.")
    if len(evidence_paths) > MAX_MEMBERS:
        raise EvidenceBundleError("Evidence bundle contains too many members.")

    members: list[EvidenceBundleMember] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()

    for raw_path in evidence_paths:
        resolved, relative_path = _relative_member_path(root, raw_path)
        try:
            evidence = read_and_validate_evidence(resolved)
        except EvidenceContractError as exc:
            raise EvidenceBundleError(
                f"Evidence member {relative_path!r} is invalid: {exc}"
            ) from exc

        if evidence.evidence_id in seen_ids:
            raise EvidenceBundleError(
                f"Duplicate evidence ID in bundle: {evidence.evidence_id}."
            )
        if relative_path in seen_paths:
            raise EvidenceBundleError(
                f"Duplicate evidence path in bundle: {relative_path}."
            )

        seen_ids.add(evidence.evidence_id)
        seen_paths.add(relative_path)
        members.append(
            EvidenceBundleMember(
                evidence_id=evidence.evidence_id,
                path=relative_path,
            )
        )

    members.sort(key=lambda member: (member.evidence_id, member.path))
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "purpose": clean_purpose,
        "members": [
            {
                "evidence_id": member.evidence_id,
                "path": member.path,
            }
            for member in members
        ],
    }
    digest = _bundle_digest(unsigned)
    return EvidenceBundle(
        schema_version=SCHEMA_VERSION,
        bundle_id=digest,
        purpose=clean_purpose,
        members=tuple(members),
    )


def write_evidence_bundle(
    bundle: EvidenceBundle,
    project: str | Path,
    output_path: str | Path,
) -> None:
    """Write a validated bundle inside the selected project root."""
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise EvidenceBundleError(f"Project directory does not exist: {root}")

    destination = Path(output_path).expanduser()
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise EvidenceBundleError(
            "Evidence bundle output must remain inside the project root."
        ) from exc

    member_descriptors = [
        {"evidence_id": member.evidence_id, "path": member.path}
        for member in bundle.members
    ]
    validated_members = _validate_members(root, member_descriptors)
    if validated_members != bundle.members:
        raise EvidenceBundleError("Evidence bundle members are not canonical.")

    member_paths = {str((root / member.path).resolve()) for member in bundle.members}
    if str(destination) in member_paths:
        raise EvidenceBundleError(
            "Evidence bundle output must not overwrite a member evidence artifact."
        )

    payload = _payload_from_bundle(bundle)
    if _bundle_digest(payload) != bundle.bundle_id:
        raise EvidenceBundleError("Evidence bundle object is internally inconsistent.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def read_and_validate_evidence_bundle(
    project: str | Path,
    bundle_path: str | Path,
) -> EvidenceBundle:
    """Validate bundle structure, identity, and every referenced evidence artifact."""
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise EvidenceBundleError(f"Project directory does not exist: {root}")

    path = Path(bundle_path).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise EvidenceBundleError(
            "Evidence bundle must remain inside the project root."
        ) from exc
    if not path.is_file():
        raise EvidenceBundleError(f"Evidence bundle does not exist: {path}")

    try:
        payload = load_json_object(path)
    except EvidenceContractError as exc:
        raise EvidenceBundleError(str(exc)) from exc

    if set(payload) != BUNDLE_KEYS:
        missing = sorted(BUNDLE_KEYS - set(payload))
        extra = sorted(set(payload) - BUNDLE_KEYS)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"unknown keys: {', '.join(extra)}")
        raise EvidenceBundleError(
            "Malformed evidence bundle schema (" + "; ".join(details) + ")."
        )

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceBundleError(
            f"Unsupported evidence bundle schema version: {payload.get('schema_version')!r}."
        )

    bundle_id = payload.get(BUNDLE_ID_KEY)
    if not isinstance(bundle_id, str) or not SHA256_RE.fullmatch(bundle_id):
        raise EvidenceBundleError("bundle_id must be a lowercase SHA-256 value.")

    purpose = _clean_purpose(payload.get("purpose"))
    members = _validate_members(root, payload.get("members"))

    canonical_payload = {
        "schema_version": SCHEMA_VERSION,
        "purpose": purpose,
        "members": [
            {
                "evidence_id": member.evidence_id,
                "path": member.path,
            }
            for member in members
        ],
    }
    calculated = _bundle_digest(canonical_payload)
    if calculated != bundle_id:
        raise EvidenceBundleError(
            "Evidence bundle identity hash is inconsistent with the canonical payload."
        )

    return EvidenceBundle(
        schema_version=SCHEMA_VERSION,
        bundle_id=bundle_id,
        purpose=purpose,
        members=members,
    )


def _to_dict(bundle: EvidenceBundle) -> dict[str, Any]:
    return _payload_from_bundle(bundle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or validate deterministic Aegis evidence bundles."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("project", type=Path)
    create.add_argument("output", type=Path)
    create.add_argument("purpose")
    create.add_argument("evidence", nargs="+", type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("project", type=Path)
    validate.add_argument("bundle", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "create":
            bundle = build_evidence_bundle(args.project, args.purpose, args.evidence)
            write_evidence_bundle(bundle, args.project, args.output)
        else:
            bundle = read_and_validate_evidence_bundle(args.project, args.bundle)
    except (EvidenceBundleError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(bundle), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
