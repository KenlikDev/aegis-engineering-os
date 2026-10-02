#!/usr/bin/env python3
"""Validate the owner-verified source marker for direct ai/integration -> develop PRs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from work_item_lifecycle import (
    GitHubIssuesProvider,
    LifecycleState,
    WorkItem,
    WorkItemLifecycleError,
)

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WORK_ITEM_RE = re.compile(r"^[1-9][0-9]*$")
WORK_ITEM_MARKER_RE = re.compile(
    r"(?m)^- Work item: #(?P<id>[1-9][0-9]*)$"
)
VERIFIED_SOURCE_RE = re.compile(
    r"(?m)^- Verified source SHA: (?P<sha>[0-9a-f]{40})$"
)


class DevelopPromotionValidationError(ValueError):
    """Raised when a direct develop promotion PR fails its provenance check."""


IssueLookup = Callable[[str], WorkItem]


def _lookup_work_item(repository: str, token: str) -> IssueLookup:
    provider = GitHubIssuesProvider(repository, token)

    def lookup(work_item_id: str) -> WorkItem:
        try:
            return provider.get(work_item_id)
        except WorkItemLifecycleError as exc:
            raise DevelopPromotionValidationError(
                f"Unable to validate work item #{work_item_id} against GitHub Issues."
            ) from exc

    return lookup


def _validate_work_item_identity(
    *,
    work_item_id: str,
    lookup: IssueLookup,
) -> None:
    try:
        item = lookup(work_item_id)
    except DevelopPromotionValidationError:
        raise
    except Exception as exc:
        raise DevelopPromotionValidationError(
            "Develop promotion work-item lookup failed closed."
        ) from exc

    if item.id != work_item_id:
        raise DevelopPromotionValidationError(
            "Develop promotion work-item identity does not match the requested marker."
        )
    if item.state != LifecycleState.INTEGRATION:
        raise DevelopPromotionValidationError(
            "Develop promotion work item must be in integration lifecycle state."
        )


def validate_event(
    event: Mapping[str, Any],
    *,
    issue_lookup: IssueLookup | None = None,
) -> None:
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
    head_repo = head.get("repo") if isinstance(head, Mapping) else None
    base_repo = base.get("repo") if isinstance(base, Mapping) else None
    body = pull_request.get("body") or ""
    if not isinstance(head_sha, str) or not SHA_RE.fullmatch(head_sha):
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR has a malformed head SHA."
        )
    if not (
        isinstance(head_repo, Mapping)
        and isinstance(base_repo, Mapping)
        and head_repo.get("full_name") == event.get("repository", {}).get("full_name")
        and base_repo.get("full_name") == event.get("repository", {}).get("full_name")
    ):
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR must originate from the configured repository."
        )
    if not isinstance(body, str):
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR body is malformed."
        )

    work_item_matches = list(WORK_ITEM_MARKER_RE.finditer(body))
    if len(work_item_matches) != 1:
        raise DevelopPromotionValidationError(
            "Direct develop promotion PR must contain exactly one "
            "authoritative work-item marker."
        )

    repository = event.get("repository")
    repository_full_name = (
        repository.get("full_name")
        if isinstance(repository, Mapping)
        else None
    )
    if not isinstance(repository_full_name, str) or not repository_full_name:
        raise DevelopPromotionValidationError(
            "GitHub event is missing the repository identity."
        )

    work_item_id = work_item_matches[0].group("id")
    if issue_lookup is None:
        raise DevelopPromotionValidationError(
            "Develop promotion work-item lookup is required."
        )
    _validate_work_item_identity(
        work_item_id=work_item_id,
        lookup=issue_lookup,
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
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not token:
            raise DevelopPromotionValidationError(
                "GITHUB_TOKEN is required to validate the develop promotion work item."
            )
        repository = event.get("repository")
        repository_full_name = (
            repository.get("full_name")
            if isinstance(repository, Mapping)
            else None
        )
        if not isinstance(repository_full_name, str) or not repository_full_name:
            raise DevelopPromotionValidationError(
                "GitHub event is missing the repository identity."
            )
        validate_event(
            event,
            issue_lookup=_lookup_work_item(repository_full_name, token),
        )
    except (OSError, json.JSONDecodeError, DevelopPromotionValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
