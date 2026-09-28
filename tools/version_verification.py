#!/usr/bin/env python3
"""Record and validate explicit project version evidence without selecting versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CLAIM_SCOPES = frozenset(
    {
        "language",
        "compiler",
        "toolchain",
        "framework",
        "runtime",
        "dependency",
        "ci",
        "container",
        "other",
    }
)


class VersionVerificationError(RuntimeError):
    """Raised when explicit version evidence cannot be validated safely."""


@dataclass(frozen=True, slots=True)
class VersionClaim:
    """One explicit version assertion tied to a source file."""

    component: str
    version: str
    scope: str
    source: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class VersionEvidence:
    """Verified version inventory for one project."""

    schema_version: int
    claims: tuple[VersionClaim, ...]
    external_verification_pending: bool

    @property
    def verified(self) -> bool:
        return bool(self.claims)


def _clean_text(value: object, field: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise VersionVerificationError(f"{field} must be a string.")
    value = value.strip()
    if not value or len(value) > max_length or any(char in value for char in "\x00\r\n"):
        raise VersionVerificationError(f"{field} must be a non-empty single-line string.")
    return value


def _relative_source(project: Path, source: str) -> tuple[Path, str]:
    relative = Path(_clean_text(source, "source"))
    if relative.is_absolute():
        resolved = relative.expanduser().resolve()
    else:
        resolved = (project / relative).resolve()
    try:
        relative_display = resolved.relative_to(project).as_posix()
    except ValueError as exc:
        raise VersionVerificationError(
            f"Version source must remain inside the project root: {source}"
        ) from exc
    return resolved, relative_display


def _sha256_and_text(path: Path) -> tuple[str, str]:
    try:
        content = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, UnicodeDecodeError) as exc:
        raise VersionVerificationError(
            f"Unable to read version source {path}: {exc}"
        ) from exc
    if not content.strip():
        raise VersionVerificationError(f"Version source is empty: {path}")
    return digest, content


def _validate_claim_input(project: Path, raw: object) -> tuple[str, str, str, str, str]:
    if not isinstance(raw, dict):
        raise VersionVerificationError("Every version claim must be an object.")
    component = _clean_text(raw.get("component"), "component")
    version = _clean_text(raw.get("version"), "version")
    scope = _clean_text(raw.get("scope"), "scope", max_length=64)
    if scope not in CLAIM_SCOPES:
        raise VersionVerificationError(
            f"Unsupported version claim scope {scope!r}; expected one of {sorted(CLAIM_SCOPES)}."
        )
    source = _clean_text(raw.get("source"), "source", max_length=1024)
    path, relative_source = _relative_source(project, source)
    digest, content = _sha256_and_text(path)
    if version not in content:
        raise VersionVerificationError(
            f"Claimed version {version!r} for {component!r} was not found in {relative_source}."
        )
    return component, version, scope, relative_source, digest


def record_version_evidence(
    project: str | Path,
    claims_path: str | Path,
    output_path: str | Path,
) -> VersionEvidence:
    """Validate explicit claims and write deterministic SHA-pinned evidence."""
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise VersionVerificationError(f"Project directory does not exist: {root}")

    claim_file = Path(claims_path).expanduser().resolve()
    try:
        payload = json.loads(claim_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VersionVerificationError(
            f"Unable to read version claim file {claim_file}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise VersionVerificationError("Version claim file must contain a JSON object.")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise VersionVerificationError(
            f"Unsupported version claim schema: {payload.get('schema_version')!r}."
        )
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        raise VersionVerificationError("Version claim file must contain at least one claim.")

    parsed: list[VersionClaim] = []
    seen: set[str] = set()
    for raw in claims:
        component, version, scope, source, digest = _validate_claim_input(root, raw)
        key = component.casefold()
        if key in seen:
            raise VersionVerificationError(
                f"Duplicate version claim component: {component!r}."
            )
        seen.add(key)
        parsed.append(
            VersionClaim(
                component=component,
                version=version,
                scope=scope,
                source=source,
                source_sha256=digest,
            )
        )

    pending = payload.get("external_verification_pending", False)
    if not isinstance(pending, bool):
        raise VersionVerificationError(
            "external_verification_pending must be boolean when provided."
        )

    evidence = VersionEvidence(
        schema_version=SCHEMA_VERSION,
        claims=tuple(parsed),
        external_verification_pending=pending,
    )

    destination = Path(output_path).expanduser()
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise VersionVerificationError(
            "Version evidence output must remain inside the project root."
        ) from exc
    if destination == claim_file:
        raise VersionVerificationError(
            "Version evidence output must differ from the claims input file."
        )
    source_paths = {
        _relative_source(root, claim["source"])[0]
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("source"), str)
    }
    if destination in source_paths:
        raise VersionVerificationError(
            "Version evidence output must not overwrite a referenced version source."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema_version": evidence.schema_version,
                "claims": [asdict(claim) for claim in evidence.claims],
                "external_verification_pending": evidence.external_verification_pending,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return evidence


def validate_version_evidence(
    project: str | Path,
    evidence_path: str | Path,
) -> VersionEvidence:
    """Validate a previously recorded evidence file against current sources."""
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise VersionVerificationError(f"Project directory does not exist: {root}")
    path = Path(evidence_path).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise VersionVerificationError(
            "Version evidence must remain inside the project root."
        ) from exc

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VersionVerificationError(
            f"Unable to read version evidence {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise VersionVerificationError("Unsupported or malformed version evidence schema.")
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        raise VersionVerificationError("Version evidence must contain at least one claim.")

    parsed: list[VersionClaim] = []
    seen: set[str] = set()
    for raw in claims:
        component, version, scope, source, digest = _validate_claim_input(root, raw)
        recorded_digest = raw.get("source_sha256") if isinstance(raw, dict) else None
        if recorded_digest != digest:
            raise VersionVerificationError(
                f"Source SHA-256 changed for {component!r}: expected {recorded_digest}, got {digest}."
            )
        key = component.casefold()
        if key in seen:
            raise VersionVerificationError(
                f"Duplicate version claim component: {component!r}."
            )
        seen.add(key)
        parsed.append(
            VersionClaim(
                component=component,
                version=version,
                scope=scope,
                source=source,
                source_sha256=digest,
            )
        )

    pending = payload.get("external_verification_pending", False)
    if not isinstance(pending, bool):
        raise VersionVerificationError(
            "external_verification_pending must be boolean when provided."
        )

    return VersionEvidence(
        schema_version=SCHEMA_VERSION,
        claims=tuple(parsed),
        external_verification_pending=pending,
    )


def _to_dict(evidence: VersionEvidence) -> dict[str, Any]:
    return {
        "schema_version": evidence.schema_version,
        "status": "verified" if evidence.verified else "blocked",
        "external_verification_pending": evidence.external_verification_pending,
        "claims": [asdict(claim) for claim in evidence.claims],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record or validate explicit project version evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record")
    record.add_argument("project", type=Path)
    record.add_argument("claims", type=Path)
    record.add_argument("--output", type=Path, default=Path(".aegis/version-evidence.json"))

    validate = subparsers.add_parser("validate")
    validate.add_argument("project", type=Path)
    validate.add_argument("evidence", type=Path)

    args = parser.parse_args()

    try:
        if args.command == "record":
            evidence = record_version_evidence(args.project, args.claims, args.output)
        else:
            evidence = validate_version_evidence(args.project, args.evidence)
    except VersionVerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(evidence), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
