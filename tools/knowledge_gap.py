#!/usr/bin/env python3
"""Track and validate Aegis knowledge-gap candidates without changing active knowledge."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid

from evidence_contract import EvidenceContractError, load_json_object, write_json_atomically
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
    transitions_sha256: str | None = None


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


def _require_text(
    value: str,
    field: str,
    maximum: int,
    *,
    reject_secret_like: bool = True,
) -> str:
    value = value.strip()
    if not value:
        raise KnowledgeGapError(f"{field} must not be empty.")
    if len(value) > maximum:
        raise KnowledgeGapError(f"{field} is too long.")
    if "\n" in value or "\r" in value:
        raise KnowledgeGapError(f"{field} must not contain newlines.")
    if reject_secret_like:
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                raise KnowledgeGapError(f"{field} contains a secret-like value.")
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
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(reference):
                raise KnowledgeGapError("Knowledge reference contains a secret-like value.")
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


def _transition_history_payload(
    transitions: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return the exact transition representation persisted to disk."""
    return list(_redact(list(transitions)))


def _transitions_sha256(
    transitions: Sequence[Mapping[str, Any]],
) -> str:
    """Hash the canonical persisted transition history."""
    return _hash(_transition_history_payload(transitions))


def _validate_transition_history(
    state: str,
    transitions: object,
) -> tuple[Mapping[str, Any], ...]:
    """Validate lifecycle transition structure and state continuity."""
    if not isinstance(transitions, list) or not transitions:
        raise KnowledgeGapError("Knowledge-gap transitions must be a non-empty list.")

    allowed = {
        None: {"candidate"},
        "candidate": {"validated", "rejected"},
        "validated": {"rejected"},
        "rejected": set(),
    }
    lifecycle_states = {"candidate", "validated", "rejected"}
    validated: list[Mapping[str, Any]] = []
    previous_state: str | None = None

    for index, raw_transition in enumerate(transitions):
        if not isinstance(raw_transition, Mapping):
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} is malformed."
            )
        if set(raw_transition) != {"from", "to", "at", "reason"}:
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} has an invalid schema."
            )

        from_state = raw_transition.get("from")
        to_state = raw_transition.get("to")
        recorded_at = raw_transition.get("at")
        reason = raw_transition.get("reason")

        if from_state != previous_state:
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} does not continue the lifecycle chain."
            )
        if from_state is not None and (
            not isinstance(from_state, str) or from_state not in lifecycle_states
        ):
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} has an invalid source state."
            )
        if not isinstance(to_state, str) or to_state not in lifecycle_states:
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} has an invalid target state."
            )
        if to_state not in allowed.get(from_state, set()):
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} contains an invalid lifecycle transition."
            )
        if not isinstance(recorded_at, str):
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} timestamp is malformed."
            )
        try:
            normalized_at = datetime.fromisoformat(
                recorded_at[:-1] + "+00:00"
                if recorded_at.endswith("Z")
                else recorded_at
            )
        except ValueError as exc:
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} timestamp is not ISO-8601."
            ) from exc
        if normalized_at.tzinfo is None:
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} timestamp must include a timezone."
            )
        if not isinstance(reason, str):
            raise KnowledgeGapError(
                f"Knowledge-gap transition {index} reason is malformed."
            )
        validated.append(
            {
                "from": from_state,
                "to": to_state,
                "at": recorded_at,
                "reason": _require_text(
                    reason,
                    f"Knowledge-gap transition {index} reason",
                    2000,
                ),
            }
        )
        previous_state = to_state

    if previous_state != state:
        raise KnowledgeGapError(
            "Knowledge-gap transition history does not terminate in the recorded state."
        )
    return tuple(validated)


def _record_to_dict(record: KnowledgeGapRecord) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "state": record.state,
        "candidate": {
            **_candidate_payload(record.candidate),
            "candidate_sha256": record.candidate.candidate_sha256,
        },
        "validation": _redact(record.validation),
        "transitions": _transition_history_payload(record.transitions),
        "transitions_sha256": record.transitions_sha256,
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

    raw_references = raw_candidate.get("references")
    if not isinstance(raw_references, list) or not all(
        isinstance(item, str) for item in raw_references
    ):
        raise KnowledgeGapError("Knowledge-gap candidate references are malformed.")

    candidate = KnowledgeGapCandidate(
        candidate_id=str(raw_candidate.get("candidate_id", "")),
        scope=str(raw_candidate.get("scope", "")),
        capability=str(raw_candidate.get("capability", "")),
        problem=str(raw_candidate.get("problem", "")),
        proposed_change=str(raw_candidate.get("proposed_change", "")),
        references=tuple(raw_references),
        created_at=str(raw_candidate.get("created_at", "")),
        candidate_sha256=str(raw_candidate.get("candidate_sha256", "")),
    )
    _validate_candidate(candidate)

    validation = data.get("validation")
    if validation is not None:
        if not isinstance(validation, Mapping):
            raise KnowledgeGapError("Knowledge-gap validation metadata is malformed.")
        validation_outcome = validation.get("outcome")
        scenario = validation.get("scenario")
        evidence_refs = validation.get("evidence_refs")
        recorded_at = validation.get("recorded_at")
        evidence_sha256 = validation.get("evidence_sha256")
        if (
            validation_outcome != "passed"
            or not isinstance(scenario, str)
            or not isinstance(evidence_refs, list)
            or not all(isinstance(item, str) for item in evidence_refs)
            or not isinstance(recorded_at, str)
            or not isinstance(evidence_sha256, str)
        ):
            raise KnowledgeGapError("Knowledge-gap validation evidence is malformed.")
        validation_payload = {
            "outcome": validation_outcome,
            "scenario": scenario,
            "evidence_refs": evidence_refs,
            "recorded_at": recorded_at,
        }
        if _hash(validation_payload) != evidence_sha256:
            raise KnowledgeGapError(
                "Knowledge-gap validation evidence hash does not match its record."
            )

    raw_transitions = data.get("transitions", [])
    transitions = _validate_transition_history(state, raw_transitions)

    raw_transitions_sha256 = data.get("transitions_sha256")
    if raw_transitions_sha256 is None:
        transitions_sha256 = None
    else:
        if not isinstance(raw_transitions_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}",
            raw_transitions_sha256,
        ):
            raise KnowledgeGapError(
                "Knowledge-gap transitions_sha256 must be a lowercase SHA-256 value."
            )
        expected_transitions_sha256 = _transitions_sha256(transitions)
        if raw_transitions_sha256 != expected_transitions_sha256:
            raise KnowledgeGapError(
                "Knowledge-gap transition history hash does not match its record."
            )
        transitions_sha256 = raw_transitions_sha256

    if state == "validated" and validation is None:
        raise KnowledgeGapError("Validated knowledge-gap record must contain validation evidence.")
    return KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state=state,
        candidate=candidate,
        validation=validation,
        transitions=transitions,
        transitions_sha256=transitions_sha256,
    )


def _read_record(path: Path) -> KnowledgeGapRecord:
    if path.is_symlink():
        raise KnowledgeGapError(f"Candidate record must not be a symbolic link: {path}")
    try:
        data = load_json_object(path)
    except FileNotFoundError as exc:
        raise KnowledgeGapError(f"Candidate record does not exist: {path}") from exc
    except (EvidenceContractError, OSError, UnicodeDecodeError) as exc:
        raise KnowledgeGapError(f"Unable to read candidate record: {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise KnowledgeGapError("Knowledge-gap record must contain a top-level object.")
    return _record_from_dict(data)


def _write_record(path: Path, record: KnowledgeGapRecord) -> None:
    payload = _record_to_dict(record)
    try:
        write_json_atomically(
            payload,
            path,
            error_type=KnowledgeGapError,
        )
    except (KnowledgeGapError, OSError) as exc:
        raise KnowledgeGapError(f"Unable to persist candidate record: {path}: {exc}") from exc


def _resolve_candidate_path(value: str | Path) -> Path:
    return Path(value).expanduser()


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
        candidate_id=candidate.candidate_id,
        scope=candidate.scope,
        capability=candidate.capability,
        problem=candidate.problem,
        proposed_change=candidate.proposed_change,
        references=candidate.references,
        created_at=candidate.created_at,
        candidate_sha256=_hash(_candidate_payload(candidate)),
    )
    _validate_candidate(candidate)
    transitions = (
        {
            "from": None,
            "to": "candidate",
            "at": created_at,
            "reason": "knowledge gap identified",
        },
    )
    record = KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state="candidate",
        candidate=candidate,
        validation=None,
        transitions=transitions,
        transitions_sha256=_transitions_sha256(transitions),
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
    scenario = _require_text(
        scenario,
        "validation scenario",
        2000,
        reject_secret_like=False,
    )
    if outcome != "passed":
        raise KnowledgeGapError("Only a passed validation outcome can create a validated candidate.")
    if not evidence_refs:
        raise KnowledgeGapError("At least one validation evidence reference is required.")
    for reference in evidence_refs:
        if not HTTPS_REFERENCE_RE.fullmatch(reference):
            raise KnowledgeGapError("Validation evidence references must use HTTPS URLs.")
    now = _now()
    validation_payload = _redact(
        {
            "outcome": "passed",
            "scenario": scenario,
            "evidence_refs": list(evidence_refs),
            "recorded_at": now,
        }
    )
    validation = {
        **validation_payload,
        "evidence_sha256": _hash(validation_payload),
    }
    transitions = record.transitions + (
        {
            "from": "candidate",
            "to": "validated",
            "at": now,
            "reason": "focused validation passed",
        },
    )
    updated = KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state="validated",
        candidate=record.candidate,
        validation=validation,
        transitions=transitions,
        transitions_sha256=_transitions_sha256(transitions),
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
    transitions = record.transitions + (
        {
            "from": record.state,
            "to": "rejected",
            "at": now,
            "reason": _require_text(reason, "rejection reason", 2000),
        },
    )
    updated = KnowledgeGapRecord(
        schema_version=SCHEMA_VERSION,
        state="rejected",
        candidate=record.candidate,
        validation=record.validation,
        transitions=transitions,
        transitions_sha256=_transitions_sha256(transitions),
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
