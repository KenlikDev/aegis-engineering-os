#!/usr/bin/env python3
"""Validate the owner-verified source marker for direct ai/integration -> develop PRs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERIFIED_SOURCE_RE = re.compile(
    r"(?m)^- Verified source SHA: (?P<sha>[0-9a-f]{40})$"
)


class DevelopPromotionValidationError(ValueError):
    """Raised when a direct develop promotion PR fails its provenance check."""


def validate_event(event: Mapping[str, Any]) -> None:
    """Validate a direct ai/integration -> develop PR event."""
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, Mapping):
        return

    base = pull_request.get("base")
    head = pull_request.get("head")
    base_ref = base.get("ref") if isinstance(base, Mapping) else None
    head_ref = head.get("ref") if isinstance(head, Mapping) else None

    if base_ref != "develop" or head_ref != "ai/integration":
        return

    head_sha = head.get("sha") if isinstance(head, Mapping) else None
    body = pull_request.get("body") or ""
    if not isinstance(head_sha, str) or not SHA_RE.fullmatch(head_sha):
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR has a malformed head SHA."
        )
    if not isinstance(body, str):
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR body is malformed."
        )

    matches = list(VERIFIED_SOURCE_RE.finditer(body))
    if len(matches) != 1:
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR must contain exactly one "
            "owner-verified source SHA marker."
        )

    verified_sha = matches[0].group("sha")
    if verified_sha != head_sha:
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR head SHA does not match its "
            "owner-verified source SHA."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate direct ai/integration -> develop promotion provenance "
            "from a GitHub event payload."
        )
    )
    parser.add_argument(
        "event_path",
        nargs="?",
        default=os.environ.get("GITHUB_EVENT_PATH"),
        help="GitHub event JSON path; defaults to GITHUB_EVENT_PATH.",
    )
    args = parser.parse_args()

    if not args.event_path:
        print("ERROR: GitHub event path is required.", file=sys.stderr)
        return 1

    try:
        event = json.loads(
            Path(args.event_path).read_text(encoding="utf-8")
        )
        if not isinstance(event, Mapping):
            raise DevelopPromotionValidationError(
                "GitHub event payload must be a JSON object."
            )
        validate_event(event)
    except (OSError, json.JSONDecodeError, DevelopPromotionValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
