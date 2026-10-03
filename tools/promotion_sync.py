#!/usr/bin/env python3
"""Synchronize a human-approved promotion merge into the Aegis work-item lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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

from promotion_readiness import (
    DEFAULT_API_BASE_URL,
    BranchSnapshot,
)
from work_item_lifecycle import (
    LifecycleState,
    Traceability,
    WorkItemLifecycleError,
    WorkItemProvider,
)

TARGETS = frozenset({"develop", "main"})
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORK_ITEM_RE = re.compile(r"^[1-9][0-9]*$")
PROMOTION_BRANCH_RE = re.compile(
    r"^ai/(?P<work_item>[1-9][0-9]*)-main-promotion$"
)
VERIFIED_SOURCE_RE = re.compile(
    r"(?m)^- Verified source SHA: (?P<sha>[0-9a-f]{40})$"
)
WORK_ITEM_MARKER_RE = re.compile(
    r"(?m)^- Work item: #(?P<id>[1-9][0-9]*)$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HTTPS_URL_RE = re.compile(r"^https://[^\s]+$")


class PromotionSyncError(RuntimeError):
    """Raised when a promotion merge cannot be synchronized safely."""


@dataclass(frozen=True, slots=True)
class PromotionPullRequest:
    """Provider-neutral promotion pull-request representation."""

    number: int
    url: str
    head: str
    head_sha: str
    base: str
    base_sha: str
    state: str
    merged: bool
    merge_commit_sha: str | None
    head_repository: str | None = None
    base_repository: str | None = None
    body: str = ""
    verified_source_sha: str | None = None
    verified_work_item_id: str | None = None


class PromotionSyncProvider(Protocol):
    """Provider-neutral read contract for promotion synchronization."""

    repository: str

    def get_pull_request(self, number: int) -> PromotionPullRequest: ...

    def get_branch(self, branch: str) -> BranchSnapshot: ...

    def target_matches_commit(self, target_branch: str, commit_sha: str) -> bool: ...


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API requests from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise PromotionSyncError("GitHub API returned an unexpected redirect.")


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
        except ValueError:
            data = {}
        return exc.code, data
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise PromotionSyncError("Unable to communicate with GitHub API.") from exc


class GitHubPromotionSyncProvider:
    """GitHub implementation of the promotion synchronization read boundary."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise PromotionSyncError("Repository must use owner/name format.")
        if not token.strip():
            raise PromotionSyncError("GitHub API token must not be empty.")
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise PromotionSyncError(str(exc)) from exc
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
            raise PromotionSyncError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            payload,
        )

    @staticmethod
    def _sha(value: Any, label: str) -> str:
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            raise PromotionSyncError(f"{label} is not a valid commit SHA.")
        return value

    def get_pull_request(self, number: int) -> PromotionPullRequest:
        if number <= 0:
            raise PromotionSyncError("Pull-request number must be positive.")
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/pulls/{number}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionSyncError(
                f"Unable to read promotion pull request #{number}; HTTP {status}."
            )

        head = data.get("head")
        base = data.get("base")
        url = data.get("html_url")
        state = data.get("state")
        merged_at = data.get("merged_at")
        body = data.get("body") or ""
        head_repo = head.get("repo") if isinstance(head, Mapping) else None
        base_repo = base.get("repo") if isinstance(base, Mapping) else None
        if (
            not isinstance(url, str)
            or not HTTPS_URL_RE.fullmatch(url)
            or not isinstance(state, str)
            or not isinstance(head_repo, Mapping)
            or not isinstance(base_repo, Mapping)
            or not isinstance(head_repo.get("full_name"), str)
            or not isinstance(base_repo.get("full_name"), str)
            or state not in {"open", "closed"}
            or not isinstance(head, Mapping)
            or not isinstance(base, Mapping)
            or not isinstance(head.get("ref"), str)
            or not isinstance(base.get("ref"), str)
            or not isinstance(body, str)
        ):
            raise PromotionSyncError("GitHub promotion pull-request response is malformed.")

        head_repository = head_repo["full_name"]
        base_repository = base_repo["full_name"]
        if head_repository != self.repository or base_repository != self.repository:
            raise PromotionSyncError(
                "GitHub promotion pull-request head and base repositories must match "
                "the configured repository."
            )

        verified_source_match = VERIFIED_SOURCE_RE.search(body)
        verified_source_sha = (
            verified_source_match.group("sha")
            if verified_source_match is not None
            else None
        )
        work_item_matches = list(WORK_ITEM_MARKER_RE.finditer(body))
        verified_work_item_id = (
            work_item_matches[0].group("id")
            if len(work_item_matches) == 1
            else None
        )

        return PromotionPullRequest(
            number=number,
            url=url,
            head=head["ref"],
            head_sha=self._sha(head.get("sha"), "Promotion pull-request head SHA"),
            base=base["ref"],
            base_sha=self._sha(base.get("sha"), "Promotion pull-request base SHA"),
            state=state,
            merged=merged_at is not None,
            merge_commit_sha=(
                self._sha(data.get("merge_commit_sha"), "Promotion merge commit SHA")
                if data.get("merge_commit_sha") is not None
                else None
            ),
            head_repository=head_repository,
            base_repository=base_repository,
            body=body,
            verified_source_sha=verified_source_sha,
            verified_work_item_id=verified_work_item_id,
        )

    def get_branch(self, branch: str) -> BranchSnapshot:
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/branches/{quote(branch, safe='')}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionSyncError(
                f"Unable to read target branch {branch!r}; HTTP {status}."
            )
        commit = data.get("commit")
        sha = commit.get("sha") if isinstance(commit, Mapping) else None
        protected = data.get("protected")
        if not isinstance(protected, bool):
            raise PromotionSyncError("GitHub target protection state is malformed.")
        return BranchSnapshot(
            branch=branch,
            sha=self._sha(sha, "Target branch SHA"),
            protected=protected,
        )

    def target_matches_commit(self, target_branch: str, commit_sha: str) -> bool:
        self._sha(commit_sha, "Promotion merge commit SHA")
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/compare/{quote(target_branch, safe='')}...{commit_sha}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionSyncError(
                f"Unable to verify merge commit ancestry in {target_branch!r}; HTTP {status}."
            )
        compare_status = data.get("status")
        ahead_by = data.get("ahead_by")
        behind_by = data.get("behind_by")
        if (
            not isinstance(compare_status, str)
            or not isinstance(ahead_by, int)
            or not isinstance(behind_by, int)
        ):
            raise PromotionSyncError("GitHub commit comparison response is malformed.")
        return compare_status == "identical" and ahead_by == 0 and behind_by == 0


def _validate_inputs(
    repository: str,
    work_item_id: str,
    pull_request_number: int,
    target_branch: str,
) -> str:
    if not REPOSITORY_RE.fullmatch(repository):
        raise PromotionSyncError("Repository must use owner/name format.")
    if not WORK_ITEM_RE.fullmatch(work_item_id):
        raise PromotionSyncError("Work-item id must be a positive integer.")
    if pull_request_number <= 0:
        raise PromotionSyncError("Pull-request number must be positive.")
    if target_branch not in TARGETS:
        raise PromotionSyncError("Promotion target must be develop or main.")
    if target_branch == "develop":
        return "ai/integration"
    expected_branch = f"ai/{work_item_id}-main-promotion"
    if not PROMOTION_BRANCH_RE.fullmatch(expected_branch):
        raise PromotionSyncError("Promotion branch name is invalid.")
    return expected_branch


def sync_promotion_merge(
    provider: PromotionSyncProvider,
    work_item_provider: WorkItemProvider,
    work_item_id: str,
    pull_request_number: int,
    *,
    target_branch: str,
) -> dict[str, Any]:
    """Advance integration to done only after a verified promotion merge."""
    expected_head = _validate_inputs(
        provider.repository,
        work_item_id,
        pull_request_number,
        target_branch,
    )

    item = work_item_provider.get(work_item_id)
    if item.state != LifecycleState.INTEGRATION:
        raise PromotionSyncError(
            "Promotion merge synchronization requires a work item in integration state; "
            f"got {item.state.value}."
        )

    target = provider.get_branch(target_branch)
    if not target.protected:
        raise PromotionSyncError(
            f"Promotion target {target_branch} must remain protected."
        )

    pull_request = provider.get_pull_request(pull_request_number)
    if pull_request.head != expected_head:
        raise PromotionSyncError(
            "Promotion pull-request head does not match the expected delivery source."
        )
    if target_branch == "develop":
        if pull_request.verified_source_sha is None:
            raise PromotionSyncError(
                "Develop promotion pull request is missing the owner-verification source SHA."
            )
        if pull_request.verified_source_sha != pull_request.head_sha:
            raise PromotionSyncError(
                "Develop promotion pull request head SHA does not match its owner-verification source SHA."
            )
        if pull_request.verified_work_item_id != work_item_id:
            raise PromotionSyncError(
                "Develop promotion pull request must contain exactly one work-item marker "
                "matching the synchronized work item."
            )
    if (
        pull_request.head_repository != provider.repository
        or pull_request.base_repository != provider.repository
    ):
        raise PromotionSyncError(
            "Promotion pull-request head and base repositories must match the configured repository."
        )
    if pull_request.base != target_branch:
        raise PromotionSyncError(
            "Promotion pull-request base does not match the selected protected target."
        )
    if not pull_request.merged or pull_request.state != "closed":
        return {
            "status": "not-merged",
            "work_item_id": work_item_id,
            "target_branch": target_branch,
            "pull_request": {
                "number": pull_request.number,
                "url": pull_request.url,
                "head": pull_request.head,
                "base": pull_request.base,
                "state": pull_request.state,
                "merged": pull_request.merged,
            },
        }

    if pull_request.merge_commit_sha is None:
        raise PromotionSyncError("Merged promotion pull request has no merge commit SHA.")

    if not provider.target_matches_commit(
        target_branch,
        pull_request.merge_commit_sha,
    ):
        raise PromotionSyncError(
            f"Promotion merge commit {pull_request.merge_commit_sha} is not exactly equal to {target_branch}."
        )

    verified_target = provider.get_branch(target_branch)
    if verified_target.sha != pull_request.merge_commit_sha:
        raise PromotionSyncError(
            f"Protected target {target_branch} advanced after exact merge verification: "
            f"observed {verified_target.sha}, expected {pull_request.merge_commit_sha}."
        )
    if not verified_target.protected:
        raise PromotionSyncError(
            f"Promotion target {target_branch} lost protected status during synchronization."
        )

    evidence_ref = (
        f"{pull_request.url}/commits/{pull_request.merge_commit_sha}"
    )
    trace = work_item_provider.attach_traceability(
        work_item_id,
        Traceability(
            pull_request_url=pull_request.url,
            evidence_ref=evidence_ref,
        ),
    )
    if not trace.verified:
        raise PromotionSyncError(
            "Promotion traceability mutation was not read-after-write verified."
        )

    mutation = work_item_provider.transition(
        work_item_id,
        LifecycleState.DONE,
        expected_state=LifecycleState.INTEGRATION,
    )
    if not mutation.verified:
        raise PromotionSyncError(
            "Promotion lifecycle transition mutation was not read-after-write verified."
        )

    final_item = work_item_provider.get(work_item_id)
    if final_item.state != LifecycleState.DONE:
        raise PromotionSyncError(
            "Work item did not verify in done state after promotion synchronization."
        )

    return {
        "status": "verified",
        "work_item_id": work_item_id,
        "target_branch": target_branch,
        "pull_request": {
            "number": pull_request.number,
            "url": pull_request.url,
            "head": pull_request.head,
            "head_repository": pull_request.head_repository,
            "base": pull_request.base,
            "base_repository": pull_request.base_repository,
            "state": pull_request.state,
            "merged": pull_request.merged,
            "merge_commit_sha": pull_request.merge_commit_sha,
        },
        "target": {
            "branch": target.branch,
            "sha": verified_target.sha,
            "protected": verified_target.protected,
        },
        "traceability_verified": trace.verified,
        "work_item": {
            "state_after": final_item.state.value,
            "transition_verified": mutation.verified,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize a verified protected-branch promotion merge."
    )
    parser.add_argument("repository")
    parser.add_argument("work_item_id")
    parser.add_argument("pull_request_number", type=int)
    parser.add_argument("target", choices=sorted(TARGETS))
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument(
        "--canonical-evidence-output",
        type=Path,
        help="Optional canonical evidence-provenance output path.",
    )
    args = parser.parse_args()

    try:
        token = os.environ.get(args.token_env, "")
        provider = GitHubPromotionSyncProvider(args.repository, token)
        work_item_provider = _build_work_item_provider(args.repository, token)
        result = sync_promotion_merge(
            provider,
            work_item_provider,
            args.work_item_id,
            args.pull_request_number,
            target_branch=args.target,
        )
    except (PromotionSyncError, WorkItemLifecycleError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    try:
        if args.canonical_evidence_output is not None:
            from evidence_adapters import promotion_sync_evidence
            from evidence_contract import write_evidence

            canonical = promotion_sync_evidence(
                result,
                repository=args.repository,
                observed_at=datetime.now(timezone.utc),
            )
            write_evidence(
                canonical,
                args.canonical_evidence_output.expanduser(),
            )
    except (OSError, ValueError, PromotionSyncError, WorkItemLifecycleError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _build_work_item_provider(repository: str, token: str) -> WorkItemProvider:
    from work_item_lifecycle import GitHubIssuesProvider

    return GitHubIssuesProvider(repository, token)


if __name__ == "__main__":
    raise SystemExit(main())
