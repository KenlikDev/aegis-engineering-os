#!/usr/bin/env python3
"""Merge verified Aegis task pull requests into ai/integration only."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from github_http_security import (
    github_api_headers,
    read_bounded_response,
    parse_github_json,
    validate_github_api_base_url,
)

from promotion_readiness import BranchSnapshot
from work_item_lifecycle import (
    LifecycleState,
    Traceability,
    WorkItemLifecycleError,
    WorkItemProvider,
)

DEFAULT_API_BASE_URL = "https://api.github.com"
INTEGRATION_BRANCH = "ai/integration"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORK_ITEM_RE = re.compile(r"^[1-9][0-9]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HTTPS_URL_RE = re.compile(r"^https://[^\s]+$")


class IntegrationMergeError(RuntimeError):
    """Raised when an integration merge cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class IntegrationPullRequest:
    """Provider-neutral pull-request state for integration merges."""

    number: int
    url: str
    head: str
    head_sha: str
    base: str
    state: str
    merged: bool
    draft: bool
    mergeable_state: str | None
    merge_commit_sha: str | None
    head_repository: str | None = None
    base_repository: str | None = None


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Result returned by a provider merge operation."""

    merged: bool
    merge_commit_sha: str | None


class IntegrationMergeProvider(Protocol):
    """Provider-neutral boundary for the only autonomous merge Aegis permits."""

    repository: str

    def get_pull_request(self, number: int) -> IntegrationPullRequest: ...

    def get_branch(self, branch: str) -> BranchSnapshot: ...

    def target_matches_commit(self, target_branch: str, commit_sha: str) -> bool: ...

    def merge_pull_request(self, number: int, expected_head_sha: str) -> MergeResult: ...


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API requests from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise IntegrationMergeError("GitHub API returned an unexpected redirect.")


_HTTP_OPENER = build_opener(_NoRedirectHandler())


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None,
) -> tuple[int, Any]:
    body = None
    request_headers = github_api_headers()
    request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    try:
        with _HTTP_OPENER.open(
            Request(url, data=body, headers=dict(request_headers), method=method),
            timeout=30.0,
        ) as response:
            raw = read_bounded_response(response)
            return response.status, parse_github_json(raw) if raw else {}
    except HTTPError as exc:
        raw = read_bounded_response(exc)
        try:
            data = parse_github_json(raw) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        return exc.code, data
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise IntegrationMergeError("Unable to communicate with GitHub API.") from exc


class GitHubIntegrationMergeProvider:
    """GitHub implementation of the controlled integration merge boundary."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise IntegrationMergeError("Repository must use owner/name format.")
        if not token.strip():
            raise IntegrationMergeError("GitHub API token must not be empty.")
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise IntegrationMergeError(str(exc)) from exc
        self.repository = repository
        self._token = token
        self._transport = transport or _default_transport
        self._api_base_url = normalized_api_base_url

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not path.startswith("/"):
            raise IntegrationMergeError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            payload,
        )

    @staticmethod
    def _sha(value: Any, label: str) -> str:
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            raise IntegrationMergeError(f"{label} is not a valid commit SHA.")
        return value

    def get_pull_request(self, number: int) -> IntegrationPullRequest:
        if number <= 0:
            raise IntegrationMergeError("Pull-request number must be positive.")
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/pulls/{number}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise IntegrationMergeError(
                f"Unable to read integration pull request #{number}; HTTP {status}."
            )
        head = data.get("head")
        base = data.get("base")
        state = data.get("state")
        url = data.get("html_url")
        head_repo = head.get("repo")
        base_repo = base.get("repo")
        if (
            not isinstance(head, Mapping)
            or not isinstance(base, Mapping)
            or not isinstance(head.get("ref"), str)
            or not isinstance(base.get("ref"), str)
            or not isinstance(head_repo, Mapping)
            or not isinstance(base_repo, Mapping)
            or not isinstance(head_repo.get("full_name"), str)
            or not isinstance(base_repo.get("full_name"), str)
            or not isinstance(state, str)
            or state not in {"open", "closed"}
            or not isinstance(url, str)
            or not HTTPS_URL_RE.fullmatch(url)
        ):
            raise IntegrationMergeError(
                "GitHub integration pull-request response is malformed."
            )

        merged_at = data.get("merged_at")
        mergeable_state = data.get("mergeable_state")
        if mergeable_state is not None and not isinstance(mergeable_state, str):
            mergeable_state = None

        return IntegrationPullRequest(
            number=number,
            url=url,
            head=head["ref"],
            head_sha=self._sha(head.get("sha"), "Pull-request head SHA"),
            base=base["ref"],
            state=state,
            merged=merged_at is not None,
            draft=bool(data.get("draft")),
            mergeable_state=mergeable_state,
            merge_commit_sha=(
                self._sha(data.get("merge_commit_sha"), "Merge commit SHA")
                if data.get("merge_commit_sha") is not None
                else None
            ),
            head_repository=head_repo["full_name"],
            base_repository=base_repo["full_name"],
        )

    def get_branch(self, branch: str) -> BranchSnapshot:
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/branches/{quote(branch, safe='')}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise IntegrationMergeError(
                f"Unable to read branch {branch!r}; HTTP {status}."
            )
        commit = data.get("commit")
        sha = commit.get("sha") if isinstance(commit, Mapping) else None
        protected = data.get("protected")
        if not isinstance(protected, bool):
            raise IntegrationMergeError("GitHub branch protection state is malformed.")
        return BranchSnapshot(
            branch=branch,
            sha=self._sha(sha, "Branch SHA"),
            protected=protected,
        )

    def target_matches_commit(self, target_branch: str, commit_sha: str) -> bool:
        self._sha(commit_sha, "Merge commit SHA")
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/compare/{quote(target_branch, safe='')}...{commit_sha}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise IntegrationMergeError(
                f"Unable to verify merge commit in {target_branch!r}; HTTP {status}."
            )
        compare_status = data.get("status")
        ahead_by = data.get("ahead_by")
        behind_by = data.get("behind_by")
        if (
            not isinstance(compare_status, str)
            or not isinstance(ahead_by, int)
            or not isinstance(behind_by, int)
        ):
            raise IntegrationMergeError("GitHub comparison response is malformed.")
        return compare_status == "identical" and ahead_by == 0 and behind_by == 0

    def merge_pull_request(
        self,
        number: int,
        expected_head_sha: str,
    ) -> MergeResult:
        self._sha(expected_head_sha, "Expected head SHA")
        status, data = self._request(
            "PUT",
            f"/repos/{self.repository}/pulls/{number}/merge",
            {
                "sha": expected_head_sha,
                "merge_method": "squash",
            },
        )
        if status not in {200, 201} or not isinstance(data, Mapping):
            raise IntegrationMergeError(
                f"GitHub refused the integration merge; HTTP {status}."
            )
        merged = data.get("merged")
        merge_commit_sha = data.get("sha")
        if not isinstance(merged, bool):
            raise IntegrationMergeError("GitHub merge response is malformed.")
        if merge_commit_sha is not None:
            merge_commit_sha = self._sha(
                merge_commit_sha,
                "Returned merge commit SHA",
            )
        return MergeResult(
            merged=merged,
            merge_commit_sha=merge_commit_sha,
        )


def _validate_request(
    repository: str,
    work_item_id: str,
    pull_request_number: int,
) -> None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise IntegrationMergeError("Repository must use owner/name format.")
    if not WORK_ITEM_RE.fullmatch(work_item_id):
        raise IntegrationMergeError("Work-item id must be a positive integer.")
    if pull_request_number <= 0:
        raise IntegrationMergeError("Pull-request number must be positive.")


def _validate_task_branch_for_work_item(branch: str, work_item_id: str) -> None:
    expected_pattern = re.compile(
        rf"^ai/(feature|fix|refactor|chore)/{re.escape(work_item_id)}-[A-Za-z0-9._-]+$"
    )
    if not expected_pattern.fullmatch(branch):
        raise IntegrationMergeError(
            "Pull-request head must be the Aegis task branch for this work item."
        )


def sync_integration_merge(
    provider: IntegrationMergeProvider,
    work_item_provider: WorkItemProvider,
    work_item_id: str,
    pull_request_number: int,
    *,
    expected_head_sha: str | None = None,
) -> dict[str, Any]:
    """Merge a verified task PR into ai/integration and synchronize lifecycle state."""
    _validate_request(provider.repository, work_item_id, pull_request_number)

    item = work_item_provider.get(work_item_id)
    if item.state != LifecycleState.REVIEW:
        raise IntegrationMergeError(
            "Integration merge requires a work item in review state; "
            f"got {item.state.value}."
        )

    integration = provider.get_branch(INTEGRATION_BRANCH)
    if not integration.protected:
        raise IntegrationMergeError("ai/integration must remain protected.")

    pull_request = provider.get_pull_request(pull_request_number)
    _validate_task_branch_for_work_item(pull_request.head, work_item_id)
    if pull_request.base != INTEGRATION_BRANCH:
        raise IntegrationMergeError(
            "Pull request base does not match ai/integration."
        )

    if pull_request.state == "closed" and not pull_request.merged:
        return {
            "status": "not-merged",
            "work_item_id": work_item_id,
            "pull_request": {
                "number": pull_request.number,
                "url": pull_request.url,
                "state": pull_request.state,
                "merged": pull_request.merged,
            },
        }

    merge_commit_sha = pull_request.merge_commit_sha
    if not pull_request.merged:
        if pull_request.draft:
            raise IntegrationMergeError(
                "Draft pull requests cannot be autonomously merged."
            )
        if pull_request.mergeable_state != "clean":
            raise IntegrationMergeError(
                "Pull request mergeable_state must be clean before autonomous integration."
            )
        if expected_head_sha is None:
            raise IntegrationMergeError(
                "An exact validation head SHA is required before merging an open pull request."
            )
        if not SHA_RE.fullmatch(expected_head_sha):
            raise IntegrationMergeError("Expected pull-request head SHA is malformed.")
        if pull_request.head_sha != expected_head_sha:
            raise IntegrationMergeError(
                "Pull request head SHA changed after validation."
            )

        result = provider.merge_pull_request(
            pull_request.number,
            pull_request.head_sha,
        )
        if not result.merged:
            raise IntegrationMergeError(
                "GitHub reported that the integration merge was not performed."
            )
        merge_commit_sha = result.merge_commit_sha
        pull_request = provider.get_pull_request(pull_request_number)

    if not pull_request.merged or pull_request.state != "closed":
        raise IntegrationMergeError(
            "Integration pull request did not verify as closed and merged."
        )

    merge_commit_sha = pull_request.merge_commit_sha or merge_commit_sha
    if merge_commit_sha is None:
        raise IntegrationMergeError("Merged integration pull request has no merge commit SHA.")

    if not provider.target_matches_commit(
        INTEGRATION_BRANCH,
        merge_commit_sha,
    ):
        raise IntegrationMergeError(
            f"ai/integration is not exactly equal to integration merge commit {merge_commit_sha}."
        )

    integration = provider.get_branch(INTEGRATION_BRANCH)
    if integration.sha != merge_commit_sha:
        raise IntegrationMergeError(
            f"ai/integration advanced after exact merge verification: "
            f"observed {integration.sha}, expected {merge_commit_sha}."
        )

    trace = work_item_provider.attach_traceability(
        work_item_id,
        Traceability(
            pull_request_url=pull_request.url,
            evidence_ref=f"{pull_request.url}/commits/{merge_commit_sha}",
        ),
    )
    if not trace.verified:
        raise IntegrationMergeError(
            "Traceability mutation was not read-after-write verified."
        )

    mutation = work_item_provider.transition(
        work_item_id,
        LifecycleState.INTEGRATION,
        expected_state=LifecycleState.REVIEW,
    )
    if not mutation.verified:
        raise IntegrationMergeError(
            "Lifecycle transition mutation was not read-after-write verified."
        )

    final_item = work_item_provider.get(work_item_id)
    if final_item.state != LifecycleState.INTEGRATION:
        raise IntegrationMergeError(
            "Work item did not verify in integration state after merge synchronization."
        )

    return {
        "status": "verified",
        "work_item_id": work_item_id,
        "validation_head_sha": expected_head_sha,
        "pull_request": {
            "number": pull_request.number,
            "url": pull_request.url,
            "head": pull_request.head,
            "head_sha": pull_request.head_sha,
            "base": pull_request.base,
            "state": pull_request.state,
            "merged": pull_request.merged,
            "merge_commit_sha": merge_commit_sha,
        },
        "integration": {
            "branch": integration.branch,
            "sha": integration.sha,
            "protected": integration.protected,
        },
        "traceability_verified": trace.verified,
        "work_item": {
            "state_after": final_item.state.value,
            "transition_verified": mutation.verified,
        },
    }


def _build_work_item_provider(repository: str, token: str) -> WorkItemProvider:
    from work_item_lifecycle import GitHubIssuesProvider

    return GitHubIssuesProvider(repository, token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge one verified Aegis task pull request into ai/integration."
    )
    parser.add_argument("repository")
    parser.add_argument("work_item_id")
    parser.add_argument("pull_request_number", type=int)
    parser.add_argument("--expected-head-sha", default=None)
    parser.add_argument(
        "--canonical-evidence-output",
        type=Path,
        help="Optional canonical evidence-provenance output path.",
    )
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()

    try:
        token = os.environ.get(args.token_env, "")
        provider = GitHubIntegrationMergeProvider(args.repository, token)
        work_item_provider = _build_work_item_provider(args.repository, token)
        result = sync_integration_merge(
            provider,
            work_item_provider,
            args.work_item_id,
            args.pull_request_number,
            expected_head_sha=args.expected_head_sha,
        )
    except (IntegrationMergeError, WorkItemLifecycleError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    if args.canonical_evidence_output is not None:
        from evidence_adapters import integration_merge_evidence
        from evidence_contract import write_evidence

        canonical = integration_merge_evidence(
            result,
            repository=args.repository,
            observed_at=datetime.now(timezone.utc),
        )
        write_evidence(
            canonical,
            Path(args.canonical_evidence_output).expanduser(),
        )

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
