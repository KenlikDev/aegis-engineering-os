#!/usr/bin/env python3
"""Prepare owner-controlled promotion snapshots without merging protected branches."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from github_http_security import (
    github_api_headers,
    read_bounded_response,
    parse_github_json,
    validate_github_api_base_url,
)

from promotion_readiness import (
    DEFAULT_SOURCE_BRANCH,
    DEFAULT_WORKFLOW,
    GitHubPromotionProvider,
    PromotionReadiness,
    PromotionReadinessError,
)

DEFAULT_API_BASE_URL = "https://api.github.com"
TARGETS = frozenset({"develop", "main"})
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORK_ITEM_RE = re.compile(r"^[1-9][0-9]*$")
PROMOTION_BRANCH_RE = re.compile(
    r"^ai/(?P<work_item>[1-9][0-9]*)-(?P<target>develop|main)-promotion$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PromotionSnapshotError(RuntimeError):
    """Raised when a promotion snapshot cannot be prepared safely."""


class PromotionSnapshotProvider(Protocol):
    """Provider-neutral contract for promotion snapshot orchestration."""

    repository: str

    def assess_readiness(
        self,
        *,
        source_branch: str,
        target_branch: str,
        workflow: str,
    ) -> PromotionReadiness: ...

    def get_commit(self, ref: str) -> GitCommitSnapshot: ...

    def is_ancestor(self, target_sha: str, source_sha: str) -> bool: ...

    def get_ref_commit(self, branch: str) -> GitCommitSnapshot | None: ...

    def create_ref(self, branch: str, sha: str) -> None: ...

    def delete_ref(self, branch: str, expected_sha: str) -> None: ...

    def create_snapshot_commit(
        self,
        *,
        message: str,
        tree_sha: str,
        target_sha: str,
        source_sha: str,
    ) -> str: ...

    def list_open_pull_requests(
        self,
        *,
        head: str,
        base: str,
    ) -> list[PullRequestSnapshot]: ...

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool,
    ) -> PullRequestSnapshot: ...


@dataclass(frozen=True, slots=True)
class GitCommitSnapshot:
    sha: str
    tree_sha: str
    parents: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PullRequestSnapshot:
    number: int
    url: str
    state: str
    merged: bool
    head: str
    base: str
    draft: bool


@dataclass(frozen=True, slots=True)
class PromotionSnapshotRequest:
    repository: str
    work_item_id: str
    target_branch: str
    source_branch: str = DEFAULT_SOURCE_BRANCH
    workflow: str = DEFAULT_WORKFLOW
    draft: bool = True


@dataclass(frozen=True, slots=True)
class PromotionSnapshotResult:
    repository: str
    work_item_id: str
    source_branch: str
    source_sha: str
    target_branch: str
    target_sha: str
    promotion_branch: str
    promotion_sha: str
    source_tree_sha: str
    pull_request: PullRequestSnapshot
    branch_reused: bool
    pull_request_reused: bool


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API calls from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise PromotionSnapshotError("GitHub API returned an unexpected redirect.")


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
        raise PromotionSnapshotError("Unable to communicate with GitHub API.") from exc


class GitHubPromotionSnapshotProvider:
    """GitHub implementation of the promotion snapshot write boundary."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise PromotionSnapshotError("Repository must use owner/name format.")
        if not token.strip():
            raise PromotionSnapshotError("GitHub API token must not be empty.")
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise PromotionSnapshotError(str(exc)) from exc
        self.repository = repository
        self._token = token
        self._transport = transport or _default_transport
        self._api_base_url = normalized_api_base_url

    def _readiness_provider(self) -> GitHubPromotionProvider:
        return GitHubPromotionProvider(
            self.repository,
            self._token,
            transport=self._transport,
            api_base_url=self._api_base_url,
        )

    def assess_readiness(
        self,
        *,
        source_branch: str,
        target_branch: str,
        workflow: str,
    ) -> PromotionReadiness:
        result = self._readiness_provider().assess(
            source_branch=source_branch,
            target_branch=target_branch,
            workflow=workflow,
        )
        if not result.ready:
            raise PromotionSnapshotError(
                "Promotion readiness is blocked: " + "; ".join(result.blockers)
            )
        return result

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not path.startswith("/"):
            raise PromotionSnapshotError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            payload,
        )

    @staticmethod
    def _require_sha(value: Any, label: str) -> str:
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            raise PromotionSnapshotError(f"{label} is not a valid commit SHA.")
        return value

    def get_commit(self, ref: str) -> GitCommitSnapshot:
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/commits/{quote(ref, safe='')}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionSnapshotError(
                f"Unable to read commit for {ref!r}; HTTP {status}."
            )
        commit_data = data.get("commit")
        tree_data = commit_data.get("tree") if isinstance(commit_data, Mapping) else None
        tree_sha = tree_data.get("sha") if isinstance(tree_data, Mapping) else None
        parents_data = data.get("parents")
        if not isinstance(parents_data, list):
            raise PromotionSnapshotError("GitHub commit parents response is malformed.")
        parents: list[str] = []
        for parent in parents_data:
            if not isinstance(parent, Mapping):
                raise PromotionSnapshotError("GitHub commit parent response is malformed.")
            parents.append(self._require_sha(parent.get("sha"), "Commit parent SHA"))
        return GitCommitSnapshot(
            sha=self._require_sha(data.get("sha"), "Commit SHA"),
            tree_sha=self._require_sha(tree_sha, "Commit tree SHA"),
            parents=tuple(parents),
        )

    def is_ancestor(self, target_sha: str, source_sha: str) -> bool:
        comparison = self._readiness_provider().compare(target_sha, source_sha)
        return (
            comparison.status == "ahead"
            and comparison.behind_by == 0
            and comparison.ahead_by > 0
        )

    def get_ref_commit(self, branch: str) -> GitCommitSnapshot | None:
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/git/ref/heads/{quote(branch, safe='')}",
        )
        if status == 404:
            return None
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionSnapshotError(
                f"Unable to read promotion branch {branch!r}; HTTP {status}."
            )
        obj = data.get("object")
        sha = obj.get("sha") if isinstance(obj, Mapping) else None
        return self.get_commit(self._require_sha(sha, "Branch ref SHA"))

    def create_ref(self, branch: str, sha: str) -> None:
        self._require_sha(sha, "Reference SHA")
        status, _ = self._request(
            "POST",
            f"/repos/{self.repository}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if status != 201:
            raise PromotionSnapshotError(
                f"Unable to create promotion branch {branch!r}; HTTP {status}."
            )

    def delete_ref(self, branch: str, expected_sha: str) -> None:
        self._require_sha(expected_sha, "Expected promotion branch SHA")
        path = f"/repos/{self.repository}/git/ref/heads/{quote(branch, safe='')}"
        status, data = self._request("GET", path)
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionSnapshotError(
                f"Unable to verify promotion branch before cleanup; HTTP {status}."
            )
        obj = data.get("object")
        current_sha = obj.get("sha") if isinstance(obj, Mapping) else None
        current_sha = self._require_sha(current_sha, "Current promotion branch SHA")
        if current_sha != expected_sha:
            raise PromotionSnapshotError(
                "Refusing promotion branch cleanup because the branch changed after publication."
            )

        status, _ = self._request("DELETE", path)
        if status != 204:
            raise PromotionSnapshotError(
                f"Unable to remove incomplete promotion branch {branch!r}; HTTP {status}."
            )

        verify_status, _ = self._request("GET", path)
        if verify_status != 404:
            raise PromotionSnapshotError(
                "Promotion branch cleanup could not be verified."
            )

    def create_snapshot_commit(
        self,
        *,
        message: str,
        tree_sha: str,
        target_sha: str,
        source_sha: str,
    ) -> str:
        self._require_sha(tree_sha, "Snapshot tree SHA")
        self._require_sha(target_sha, "Target SHA")
        self._require_sha(source_sha, "Source SHA")
        status, data = self._request(
            "POST",
            f"/repos/{self.repository}/git/commits",
            {
                "message": message,
                "tree": tree_sha,
                "parents": [target_sha, source_sha],
            },
        )
        if status != 201 or not isinstance(data, Mapping):
            raise PromotionSnapshotError(
                f"Unable to create promotion snapshot commit; HTTP {status}."
            )
        return self._require_sha(data.get("sha"), "Promotion commit SHA")

    def list_open_pull_requests(
        self,
        *,
        head: str,
        base: str,
    ) -> list[PullRequestSnapshot]:
        owner = self.repository.split("/", 1)[0]
        query = urlencode(
            {
                "state": "open",
                "head": f"{owner}:{head}",
                "base": base,
                "per_page": "20",
            }
        )
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/pulls?{query}",
        )
        if status != 200 or not isinstance(data, list):
            raise PromotionSnapshotError(
                f"Unable to list open promotion pull requests; HTTP {status}."
            )
        result: list[PullRequestSnapshot] = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            parsed = self._parse_pull_request(item)
            if parsed is not None and parsed.head == head and parsed.base == base:
                result.append(parsed)
        return result

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool,
    ) -> PullRequestSnapshot:
        status, data = self._request(
            "POST",
            f"/repos/{self.repository}/pulls",
            {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": draft,
                "maintainer_can_modify": False,
            },
        )
        if status != 201 or not isinstance(data, Mapping):
            raise PromotionSnapshotError(
                f"Unable to create promotion pull request; HTTP {status}."
            )
        parsed = self._parse_pull_request(data)
        if parsed is None:
            raise PromotionSnapshotError("GitHub pull-request response is malformed.")
        return parsed

    @staticmethod
    def _parse_pull_request(data: Mapping[str, Any]) -> PullRequestSnapshot | None:
        number = data.get("number")
        url = data.get("html_url")
        state = data.get("state")
        merged = data.get("merged", False)
        head = data.get("head")
        base = data.get("base")
        draft = data.get("draft", False)
        head_ref = head.get("ref") if isinstance(head, Mapping) else None
        base_ref = base.get("ref") if isinstance(base, Mapping) else None
        if not (
            isinstance(number, int)
            and isinstance(url, str)
            and isinstance(state, str)
            and isinstance(merged, bool)
            and isinstance(head_ref, str)
            and isinstance(base_ref, str)
            and isinstance(draft, bool)
        ):
            return None
        return PullRequestSnapshot(
            number=number,
            url=url,
            state=state,
            merged=merged,
            head=head_ref,
            base=base_ref,
            draft=draft,
        )


def _validate_request(request: PromotionSnapshotRequest) -> None:
    if not REPOSITORY_RE.fullmatch(request.repository):
        raise PromotionSnapshotError("Repository must use owner/name format.")
    if not WORK_ITEM_RE.fullmatch(request.work_item_id):
        raise PromotionSnapshotError("Work-item id must be a positive integer.")
    if request.source_branch != DEFAULT_SOURCE_BRANCH:
        raise PromotionSnapshotError("Promotion source must be ai/integration.")
    if request.target_branch not in TARGETS:
        raise PromotionSnapshotError("Promotion target must be develop or main.")
    expected = f"ai/{request.work_item_id}-{request.target_branch}-promotion"
    if not PROMOTION_BRANCH_RE.fullmatch(expected):
        raise PromotionSnapshotError("Promotion branch name is invalid.")


def _ensure_ready(
    provider: PromotionSnapshotProvider,
    request: PromotionSnapshotRequest,
) -> tuple[GitCommitSnapshot, GitCommitSnapshot]:
    readiness = provider.assess_readiness(
        source_branch=request.source_branch,
        target_branch=request.target_branch,
        workflow=request.workflow,
    )

    source = provider.get_commit(readiness.source.sha)
    target = provider.get_commit(readiness.target.sha)

    if source.sha != readiness.source.sha or target.sha != readiness.target.sha:
        raise PromotionSnapshotError(
            "Promotion readiness commit identity changed while loading the validated snapshot."
        )
    if source.sha == target.sha:
        raise PromotionSnapshotError("Promotion contains no delta.")
    if not provider.is_ancestor(target.sha, source.sha):
        raise PromotionSnapshotError(
            "Promotion target is not an ancestor of ai/integration."
        )
    return source, target



def prepare_promotion_snapshot(
    provider: PromotionSnapshotProvider,
    request: PromotionSnapshotRequest,
) -> PromotionSnapshotResult:
    """Create or reuse a verified promotion snapshot and open/reuse its PR."""
    _validate_request(request)
    source, target = _ensure_ready(provider, request)
    branch = f"ai/{request.work_item_id}-{request.target_branch}-promotion"

    existing_branch = provider.get_ref_commit(branch)
    branch_reused = existing_branch is not None
    branch_published = False

    try:
        if existing_branch is not None:
            if (
                existing_branch.parents != (target.sha, source.sha)
                or existing_branch.tree_sha != source.tree_sha
            ):
                raise PromotionSnapshotError(
                    f"Existing promotion branch {branch!r} does not match the current snapshot."
                )
            promotion_sha = existing_branch.sha
        else:
            promotion_sha = provider.create_snapshot_commit(
                message=(
                    f"chore: prepare promotion snapshot for #{request.work_item_id} "
                    f"to {request.target_branch}"
                ),
                tree_sha=source.tree_sha,
                target_sha=target.sha,
                source_sha=source.sha,
            )

            current_source = provider.get_commit(request.source_branch)
            current_target = provider.get_commit(request.target_branch)
            if current_source.sha != source.sha:
                raise PromotionSnapshotError(
                    "ai/integration changed while the promotion snapshot was being prepared."
                )
            if current_target.sha != target.sha:
                raise PromotionSnapshotError(
                    f"{request.target_branch} changed while the promotion snapshot was being prepared."
                )

            provider.create_ref(branch, promotion_sha)
            branch_published = True

        verified = provider.get_ref_commit(branch)
        if verified is None:
            raise PromotionSnapshotError("Promotion branch disappeared after creation.")
        if (
            verified.parents != (target.sha, source.sha)
            or verified.tree_sha != source.tree_sha
            or verified.sha != promotion_sha
        ):
            raise PromotionSnapshotError(
                "Promotion branch verification failed after snapshot creation."
            )

        existing_prs = provider.list_open_pull_requests(
            head=branch,
            base=request.target_branch,
        )
        if len(existing_prs) > 1:
            raise PromotionSnapshotError(
                "Multiple open promotion pull requests exist for the same branch pair."
            )

        pr_reused = bool(existing_prs)
        if existing_prs:
            pull_request = existing_prs[0]
        else:
            pull_request = provider.create_pull_request(
                title=(
                    f"chore: promote ai/integration to {request.target_branch} "
                    f"(#{request.work_item_id})"
                ),
                body=(
                    "## Aegis promotion snapshot\n\n"
                    f"- Work item: #{request.work_item_id}\n"
                    f"- Source: {request.source_branch} at {source.sha}\n"
                    f"- Target: {request.target_branch} at {target.sha}\n"
                    f"- Snapshot branch: {branch} at {promotion_sha}\n\n"
                    "This pull request is a prepared promotion artifact. "
                    "Aegis does not approve or merge protected branches."
                ),
                head=branch,
                base=request.target_branch,
                draft=request.draft,
            )

        if (
            pull_request.head != branch
            or pull_request.base != request.target_branch
            or pull_request.state != "open"
            or pull_request.merged
        ):
            raise PromotionSnapshotError("Promotion pull request verification failed.")
    except Exception as exc:
        if not branch_published:
            raise
        try:
            provider.delete_ref(branch, promotion_sha)
        except Exception as cleanup_error:
            raise PromotionSnapshotError(
                "Promotion snapshot preparation failed and cleanup of the newly "
                f"published branch also failed: {cleanup_error}"
            ) from exc
        raise

    return PromotionSnapshotResult(
        repository=request.repository,
        work_item_id=request.work_item_id,
        source_branch=request.source_branch,
        source_sha=source.sha,
        target_branch=request.target_branch,
        target_sha=target.sha,
        promotion_branch=branch,
        promotion_sha=promotion_sha,
        source_tree_sha=source.tree_sha,
        pull_request=pull_request,
        branch_reused=branch_reused,
        pull_request_reused=pr_reused,
    )


def _to_dict(result: PromotionSnapshotResult) -> dict[str, Any]:
    return {
        "status": "prepared",
        "repository": result.repository,
        "work_item_id": result.work_item_id,
        "source": {"branch": result.source_branch, "sha": result.source_sha},
        "target": {"branch": result.target_branch, "sha": result.target_sha},
        "promotion_branch": result.promotion_branch,
        "promotion_sha": result.promotion_sha,
        "source_tree_sha": result.source_tree_sha,
        "branch_reused": result.branch_reused,
        "pull_request_reused": result.pull_request_reused,
        "pull_request": {
            "number": result.pull_request.number,
            "url": result.pull_request.url,
            "state": result.pull_request.state,
            "merged": result.pull_request.merged,
            "head": result.pull_request.head,
            "base": result.pull_request.base,
            "draft": result.pull_request.draft,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare an owner-controlled Aegis promotion snapshot."
    )
    parser.add_argument("repository")
    parser.add_argument("work_item_id")
    parser.add_argument("target", choices=sorted(TARGETS))
    parser.add_argument("--source", default=DEFAULT_SOURCE_BRANCH)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument(
        "--ready",
        action="store_true",
        help="Create the promotion pull request as ready for review.",
    )
    args = parser.parse_args()

    try:
        token = os.environ.get(args.token_env, "")
        provider = GitHubPromotionSnapshotProvider(args.repository, token)
        result = prepare_promotion_snapshot(
            provider,
            PromotionSnapshotRequest(
                repository=args.repository,
                work_item_id=args.work_item_id,
                target_branch=args.target,
                source_branch=args.source,
                workflow=args.workflow,
                draft=not args.ready,
            ),
        )
    except (PromotionSnapshotError, PromotionReadinessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    print(json.dumps(_to_dict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
