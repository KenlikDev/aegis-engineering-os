#!/usr/bin/env python3
"""Track and validate Aegis knowledge-gap candidates without changing active knowledge."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_STORE_ROOT = Path(".aegis") / "knowledge" / "candidates"
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)
HTTPS_REFERENCE_RE = re.compile(r"^https://[^\s]+$")
SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|credential)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9_]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
)


class KnowledgeGapError(RuntimeError):
    """Raised when a knowledge-gap operation cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class KnowledgeGapCandidate:
    """Provider-neutral immutable candidate payload."""

    candidate_id: str
    scope: str
    capability: str
    problem: str
    proposed_change: str
    references: tuple[str, ...]
    created_at: str
    candidate_sha256: str


@dataclass(frozen=True, slots=True)
class KnowledgeGapRecord:
    """Persisted candidate record with controlled lifecycle metadata."""

    schema_version: int
    state: str
    candidate: KnowledgeGapCandidate
    validation: Mapping[str, Any] | None
    transitions: tuple[Mapping[str, Any], ...]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if SECRET_KEY_RE.search(str(key))
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_VALUE_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


def _require_text(value: str, field: str, maximum: int) -> str:
    value = value.strip()
    if not value:
        raise KnowledgeGapError(f"{field} must not be empty.")
    if len(value) > maximum:
        raise KnowledgeGapError(f"{field} is too long.")
    if "\n" in value or "\r" in value:
        raise KnowledgeGapError(f"{field} must not contain newlines.")
    return value


def _validate_candidate(candidate: KnowledgeGapCandidate) -> None:
    if not UUID_RE.fullmatch(candidate.candidate_id):
        raise KnowledgeGapError("Candidate id must be a UUID.")
    if candidate.scope not in {"global", "project"}:
        raise KnowledgeGapError("Candidate scope must be global or project.")
    _require_text(candidate.capability, "capability", 200)
    _require_text(candidate.problem, "problem", 2000)
    _require_text(candidate.proposed_change, "proposed_change", 4000)
    if not candidate.references:
        raise KnowledgeGapError("At least one provenance reference is required.")
    for reference in candidate.references:
        if not HTTPS_REFERENCE_RE.fullmatch(reference):
            raise KnowledgeGapError("Knowledge references must use HTTPS URLs.")
        if len(reference) > 1000:
            raise KnowledgeGapError("Knowledge reference is too long.")
    payload = {
        "candidate_id": candidate.candidate_id,
        "scope": candidate.scope,
        "capability": candidate.capability,
        "problem": candidate.problem,
        "proposed_change": candidate.proposed_change,
        "references": list(candidate.references),
        "created_at": candidate.created_at,
    }
    if _hash(payload) != candidate.candidate_sha256:
        raise KnowledgeGapError("Candidate provenance hash does not match its original payload.")


def _candidate_payload(candidate: KnowledgeGapCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "scope": candidate.scope,
        "capability": candidate.capability,
        "problem": candidate.problem,
        "proposed_change": candidate.proposed_change,
        "references": list(candidate.references),
        "created_at": candidate.created_at,
    }


def _record_to_dict(record: KnowledgeGapRecord) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "state": record.state,
        "candidate": {
            **_candidate_payload(record.candidate),
            "candidate_sha256": record.candidate.candidate_sha256,
        },
        "validation": _redact(record.validation),
        "transitions": _redact(list(record.transitions)),
    }


def _record_from_dict(data: Mapping[str, Any]) -> KnowledgeGapRecord:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise KnowledgeGapError("Unsupported knowledge-gap record schema version.")
    state = data.get("state")
    if state not in {"candidate", "validated", "rejected"}:
        raise KnowledgeGapError("Knowledge-gap record contains an invalid state.")

    raw_candidate = data.get("candidate")
    if not isinstance(raw_candidate, Mapping):
        raise KnowledgeGapError("Knowledge-gap candidate payload is malformed.")

    candidate = KnowledgeGapCandidate(
        candidate_id=str(raw_candidate.get("candidate_id", "")),
        scope=str(raw_candidate.get("scope", "")),
        capability=str(raw_candidate.get("capability", "")),
        problem=str(raw_candidate.get("problem", "")),
        proposed_change=str(raw_candidate.get("proposed_change", "")),
        references=tuple(
            item for item in raw_candidate.get("references", [])
            if isinstance(item, str)
        ),
        created_at=str(raw_candidate.get("created_at", "")),
        candidate_sha256=str(raw_candidate.get("candidate_sha256", "")),
    )
    _validate_candidate(candidate)

    validation = data.get("validation")
    if validation is not None and not isinstance(validation, Mapping):
        raise KnowledgeGapError("Knowledge-gap validation metadata is malformed.")

    raw_transitions = data.get("transitions", [])
    if not isinstance(raw_transitions, list):
        raise KnowledgeGapError("Knowledge-gap transitions must be a list.")
    transitions: list[Mapping[str, Any]] = []
    for transition in raw_transitions:
        if not isinstance(transition, Mapping):
            raise KnowledgeGapError("Knowledge-gap transition entry is malformed.")
        transitions.append(dict(transition))

    if state == "validated" and validation is None:
        raise KnowledgeGapError("Validated knowledge-gap record must contain validation evidence.")
    return KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state=state,
        candidate=candidate,
        validation=validation,
        transitions=tuple(transitions),
    )


def _read_record(path: Path) -> KnowledgeGapRecord:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KnowledgeGapError(f"Candidate record does not exist: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeGapError(f"Unable to read candidate record: {path}") from exc
    if not isinstance(data, Mapping):
        raise KnowledgeGapError("Knowledge-gap record must contain a top-level object.")
    return _record_from_dict(data)


def _write_record(path: Path, record: KnowledgeGapRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = _record_to_dict(record)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise KnowledgeGapError(f"Unable to persist candidate record: {path}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _resolve_candidate_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def create_candidate(
    *,
    scope: str,
    capability: str,
    problem: str,
    proposed_change: str,
    references: Sequence[str],
    store_root: str | Path = DEFAULT_STORE_ROOT,
    candidate_id: str | None = None,
) -> KnowledgeGapRecord:
    """Create a candidate record without registering or activating knowledge."""
    if scope not in {"global", "project"}:
        raise KnowledgeGapError("Candidate scope must be global or project.")
    identifier = candidate_id or str(uuid.uuid4())
    created_at = _now()
    candidate = KnowledgeGapCandidate(
        candidate_id=identifier,
        scope=scope,
        capability=_require_text(capability, "capability", 200),
        problem=_require_text(problem, "problem", 2000),
        proposed_change=_require_text(proposed_change, "proposed_change", 4000),
        references=tuple(references),
        created_at=created_at,
        candidate_sha256="",
    )
    candidate = KnowledgeGapCandidate(
        **{
            **candidate.__dict__,
            "candidate_sha256": _hash(_candidate_payload(candidate)),
        }
    )
    _validate_candidate(candidate)
    record = KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state="candidate",
        candidate=candidate,
        validation=None,
        transitions=(
            {
                "from": None,
                "to": "candidate",
                "at": created_at,
                "reason": "knowledge gap identified",
            },
        ),
    )
    path = _resolve_candidate_path(store_root) / f"{identifier}.json"
    if path.exists():
        raise KnowledgeGapError(f"Candidate record already exists: {path}")
    _write_record(path, record)
    return record


def validate_candidate(
    path: str | Path,
    *,
    scenario: str,
    evidence_refs: Sequence[str],
    outcome: str = "passed",
) -> KnowledgeGapRecord:
    """Move candidate -> validated only with explicit passed evidence."""
    candidate_path = _resolve_candidate_path(path)
    record = _read_record(candidate_path)
    if record.state != "candidate":
        raise KnowledgeGapError(
            f"Knowledge-gap validation requires candidate state; got {record.state}."
        )
    scenario = _require_text(scenario, "validation scenario", 2000)
    if outcome != "passed":
        raise KnowledgeGapError("Only a passed validation outcome can create a validated candidate.")
    if not evidence_refs:
        raise KnowledgeGapError("At least one validation evidence reference is required.")
    for reference in evidence_refs:
        if not HTTPS_REFERENCE_RE.fullmatch(reference):
            raise KnowledgeGapError("Validation evidence references must use HTTPS URLs.")
    now = _now()
    validation = {
        "outcome": "passed",
        "scenario": scenario,
        "evidence_refs": list(evidence_refs),
        "recorded_at": now,
        "evidence_sha256": _hash(
            {
                "outcome": "passed",
                "scenario": scenario,
                "evidence_refs": list(evidence_refs),
                "recorded_at": now,
            }
        ),
    }
    updated = KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state="validated",
        candidate=record.candidate,
        validation=validation,
        transitions=record.transitions
        + (
            {
                "from": "candidate",
                "to": "validated",
                "at": now,
                "reason": "focused validation passed",
            },
        ),
    )
    _write_record(candidate_path, updated)
    return updated


def reject_candidate(path: str | Path, *, reason: str) -> KnowledgeGapRecord:
    """Reject a candidate without changing any active knowledge."""
    candidate_path = _resolve_candidate_path(path)
    record = _read_record(candidate_path)
    if record.state not in {"candidate", "validated"}:
        raise KnowledgeGapError(
            f"Knowledge-gap rejection requires candidate or validated state; got {record.state}."
        )
    now = _now()
    updated = KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state="rejected",
        candidate=record.candidate,
        validation=record.validation,
        transitions=record.transitions
        + (
            {
                "from": record.state,
                "to": "rejected",
                "at": now,
                "reason": _require_text(reason, "rejection reason", 2000),
            },
        ),
    )
    _write_record(candidate_path, updated)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create and validate Aegis knowledge-gap candidate records."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--scope", required=True, choices=("global", "project"))
    create.add_argument("--capability", required=True)
    create.add_argument("--problem", required=True)
    create.add_argument("--proposed-change", required=True)
    create.add_argument("--reference", action="append", required=True)
    create.add_argument("--store-root", default=str(DEFAULT_STORE_ROOT))
    create.add_argument("--candidate-id")

    validate = sub.add_parser("validate")
    validate.add_argument("path")
    validate.add_argument("--scenario", required=True)
    validate.add_argument("--evidence-ref", action="append", required=True)
    validate.add_argument("--outcome", default="passed")

    reject = sub.add_parser("reject")
    reject.add_argument("path")
    reject.add_argument("--reason", required=True)

    args = parser.parse_args()
    try:
        if args.command == "create":
            record = create_candidate(
                scope=args.scope,
                capability=args.capability,
                problem=args.problem,
                proposed_change=args.proposed_change,
                references=args.reference,
                store_root=args.store_root,
                candidate_id=args.candidate_id,
            )
            path = _resolve_candidate_path(args.store_root) / f"{record.candidate.candidate_id}.json"
        elif args.command == "validate":
            record = validate_candidate(
                args.path,
                scenario=args.scenario,
                evidence_refs=args.evidence_ref,
                outcome=args.outcome,
            )
            path = _resolve_candidate_path(args.path)
        else:
            record = reject_candidate(args.path, reason=args.reason)
            path = _resolve_candidate_path(args.path)
    except KnowledgeGapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = _record_to_dict(record)
    output["path"] = str(path)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
