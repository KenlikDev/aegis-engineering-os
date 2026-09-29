#!/usr/bin/env python3
"""Record and validate provider-neutral state-verification evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evidence_contract import (
    EvidenceContractError,
    build_evidence,
    load_json_object,
    read_and_validate_evidence,
    write_evidence,
)


def record_state_evidence(input_path: str | Path, output_path: str | Path):
    """Record explicit observed state without mutating the observed system."""
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_path).expanduser()
    resolved_destination = destination.resolve()
    if source == resolved_destination:
        raise EvidenceContractError("Evidence input and output paths must differ.")
    payload = load_json_object(source)
    record = build_evidence(payload)
    write_evidence(record, destination)
    return record


def _to_dict(record: Any) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "evidence_id": record.evidence_id,
        "kind": record.kind,
        "source": record.source,
        "subject": record.subject,
        "revision": record.revision,
        "observed_at": record.observed_at,
        "status": record.status,
        "result": record.result,
        "uncertainty": list(record.uncertainty),
        "references": list(record.references),
        "artifact_sha256": record.artifact_sha256,
        "evidence_sha256": record.evidence_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record or validate provider-neutral state evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record")
    record.add_argument("input", type=Path)
    record.add_argument("output", type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("evidence", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "record":
            result = record_state_evidence(args.input, args.output)
        else:
            result = read_and_validate_evidence(args.evidence)
    except (EvidenceContractError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
