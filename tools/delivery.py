#!/usr/bin/env python3
"""Create and verify pull requests for Aegis work items.

The delivery layer is intentionally separate from project execution. It creates
pull requests only after a work item reaches review and never merges them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from github_http_security import (
    read_bounded_response,
    validate_github_api_base_url,
)

from work_item_lifecycle import (
    LifecycleState,
    Traceability,
    WorkItemLifecycleError,
    WorkItemProvider,
)

GITHUB_API_VERSION = "2026-03-10"
DEFAULT_API_BASE_URL = "https://api.github.com"
TASK_BRANCH_RE = re.compile(
    r"^ai/(feature|fix|refactor|chore)/[A-Za-z0-9._-]+$"
)
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HTTPS_URL_RE = re.compile(r"^https://[^\s]+$")


class DeliveryError(RuntimeError):
    """Raised when delivery lifecycle work cannot be completed safely."""


class PullRequestProvider(Protocol):
    """Provider-neutral pull-request operations required by Aegis."""

    def find_open(self, head: str, base: str) -> PullRequest | None:
        ...

    def get(self, pull_request_number: int) -> PullRequest:
        ...

    def create(self, request: CreatePullRequestRequest) -> MutationEvidence:
        ...


@dataclass(frozen=True, slots=True)
class PullRequest:
    """Provider-neutral pull-request representation."""

    number: int
    title: str
    body: str
    head: str
    base: str
    state: str
    merged: bool
    draft: bool
    mergeable: bool | None
    mergeable_state: str | None
    url: str


@dataclass(frozen=True, slots=True)
class CreatePullRequestRequest:
    """Explicit source/target pull-request creation request."""

    repository: str
    head: str
    base: str
    title: str
    body: str
    draft: bool = False


@dataclass(frozen=True, slots=True)
class MutationEvidence:
    """Verified evidence for a provider mutation or idempotent reuse."""

    provider: str
    operation: str
    reference: str
    verified: bool
    identifier: int | str | None = None


def _validate_repository(repository: str) -> str:
    if not REPOSITORY_RE.fullmatch(repository):
        raise DeliveryError("Repository must use owner/name format.")
    return repository


def _validate_task_branch(branch: str) -> str:
    if not TASK_BRANCH_RE.fullmatch(branch):
        raise DeliveryError("Pull-request head must use the Aegis ai/* task-branch policy.")
    return branch


def _validate_base_branch(branch: str) -> str:
    if not branch or not BRANCH_RE.fullmatch(branch):
        raise DeliveryError("Pull-request base branch is invalid.")
    if branch in {"main", "develop"}:
        raise DeliveryError("This delivery bridge cannot target protected main or develop.")
    if not branch.startswith("ai/"):
        raise DeliveryError("This delivery bridge requires an ai/* integration target.")
    return branch


def _validate_request(request: CreatePullRequestRequest) -> None:
    _validate_repository(request.repository)
    _validate_task_branch(request.head)
    _validate_base_branch(request.base)
    if request.head == request.base:
        raise DeliveryError("Pull-request head and base branches must differ.")
    if not request.title.strip():
        raise DeliveryError("Pull-request title must not be empty.")
    if len(request.title) > 256:
        raise DeliveryError("Pull-request title is too long.")
    if len(request.body) > 65536:
        raise DeliveryError("Pull-request body is too long.")


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API requests from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise DeliveryError("GitHub API returned an unexpected redirect.")


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]

_HTTP_OPENER = build_opener(_NoRedirectHandler())


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None,
) -> tuple[int, Any]:
    body = None
    request_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(
        url,
        data=body,
        headers=dict(request_headers),
        method=method,
    )
    try:
        with _HTTP_OPENER.open(request, timeout=30.0) as response:
            raw = read_bounded_response(response)
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        raw = read_bounded_response(exc)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        return exc.code, data
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryError(f"Unable to communicate with GitHub API endpoint: {exc}") from exc


class GitHubPullRequestProvider:
    """GitHub implementation of the Aegis pull-request provider contract."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        self.repository = _validate_repository(repository)
        if not token.strip():
            raise DeliveryError("GitHub API token must not be empty.")
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise DeliveryError(str(exc)) from exc
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
            raise DeliveryError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            payload,
        )

    def _pull_request_path(self, number: int) -> str:
        if number <= 0:
            raise DeliveryError("Pull-request number must be positive.")
        return f"/repos/{self.repository}/pulls/{number}"

    @staticmethod
    def _parse(data: Mapping[str, Any]) -> PullRequest:
        number = data.get("number")
        title = data.get("title")
        body = data.get("body") or ""
        head = data.get("head")
        base = data.get("base")
        state = data.get("state")
        url = data.get("html_url")
        if (
            not isinstance(number, int)
            or not isinstance(title, str)
            or not isinstance(body, str)
            or not isinstance(head, Mapping)
            or not isinstance(base, Mapping)
            or not isinstance(head.get("ref"), str)
            or not isinstance(base.get("ref"), str)
            or not isinstance(state, str)
            or not isinstance(url, str)
            or not HTTPS_URL_RE.fullmatch(url)
        ):
            raise DeliveryError("GitHub pull-request response is malformed.")
        if state not in {"open", "closed"}:
            raise DeliveryError(
                f"Unsupported GitHub pull-request state: {state!r}."
            )
        merged_at = data.get("merged_at")
        if merged_at is not None and state != "closed":
            raise DeliveryError(
                "GitHub pull request reports merged_at while still open."
            )
        if merged_at is not None and not isinstance(merged_at, str):
            raise DeliveryError("GitHub pull request merged_at field is malformed.")
        mergeable = data.get("mergeable")
        if mergeable is not None and not isinstance(mergeable, bool):
            mergeable = None
        mergeable_state = data.get("mergeable_state")
        if mergeable_state is not None and not isinstance(mergeable_state, str):
            mergeable_state = None
        draft = data.get("draft")
        return PullRequest(
            number=number,
            title=title,
            body=body,
            head=head["ref"],
            base=base["ref"],
            state=state,
            merged=merged_at is not None,
            draft=bool(draft),
            mergeable=mergeable,
            mergeable_state=mergeable_state,
            url=url,
        )

    def get(self, pull_request_number: int) -> PullRequest:
        status, data = self._request(
            "GET",
            self._pull_request_path(pull_request_number),
        )
        if status != 200 or not isinstance(data, Mapping):
            raise DeliveryError(
                f"Unable to read pull request #{pull_request_number}; HTTP {status}."
            )
        return self._parse(data)

    def find_open(self, head: str, base: str) -> PullRequest | None:
        _validate_task_branch(head)
        _validate_base_branch(base)
        query = urlencode(
            {
                "state": "open",
                "head": f"{self.repository.split('/', 1)[0]}:{head}",
                "base": base,
                "per_page": "20",
            }
        )
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/pulls?{query}",
        )
        if status != 200 or not isinstance(data, list):
            raise DeliveryError(
                f"Unable to search for open pull requests; HTTP {status}."
            )
        matches = [
            self._parse(item)
            for item in data
            if isinstance(item, Mapping)
        ]
        exact = [
            item
            for item in matches
            if item.head == head and item.base == base and not item.merged
        ]
        if len(exact) > 1:
            raise DeliveryError(
                "GitHub returned multiple open pull requests for the same head/base pair."
            )
        return exact[0] if exact else None

    def create(self, request: CreatePullRequestRequest) -> MutationEvidence:
        _validate_request(request)
        existing = self.find_open(request.head, request.base)
        if existing is not None:
            return MutationEvidence(
                provider="github-pull-requests",
                operation="reuse_existing",
                reference=existing.url,
                verified=True,
                identifier=existing.number,
            )

        status, data = self._request(
            "POST",
            f"/repos/{self.repository}/pulls",
            {
                "title": request.title,
                "body": request.body,
                "head": request.head,
                "base": request.base,
                "draft": request.draft,
            },
        )
        if status not in {201, 200} or not isinstance(data, Mapping):
            raise DeliveryError(
                f"Unable to create pull request; HTTP {status}."
            )
        number = data.get("number")
        if not isinstance(number, int):
            raise DeliveryError("GitHub pull-request creation returned no number.")
        created = self.get(number)
        if created.head != request.head or created.base != request.base:
            raise DeliveryError(
                "GitHub pull request did not verify with the requested head/base branches."
            )
        return MutationEvidence(
            provider="github-pull-requests",
            operation="create",
            reference=created.url,
            verified=True,
            identifier=created.number,
        )


def create_review_pull_request(
    provider: PullRequestProvider,
    work_item_provider: WorkItemProvider,
    work_item_id: str,
    request: CreatePullRequestRequest,
) -> dict[str, Any]:
    """Create or reuse a PR only for a work item already in review."""
    _validate_request(request)
    item = work_item_provider.get(work_item_id)
    if item.state != LifecycleState.REVIEW:
        raise DeliveryError(
            "Pull-request creation requires a work item in review state; "
            f"got {item.state.value}."
        )

    mutation = provider.create(request)
    if not mutation.verified:
        raise DeliveryError(
            "Pull-request creation mutation was not read-after-write verified."
        )
    if not isinstance(mutation.identifier, int) or mutation.identifier <= 0:
        raise DeliveryError(
            "Pull-request creation provider did not return a numeric pull-request identifier."
        )
    pull_number = mutation.identifier
    pull_request = provider.get(pull_number)
    if pull_request.head != request.head or pull_request.base != request.base:
        raise DeliveryError("Pull-request traceability verification failed.")

    trace = work_item_provider.attach_traceability(
        work_item_id,
        Traceability(
            branch=pull_request.head,
            pull_request_url=pull_request.url,
        ),
    )
    if not trace.verified:
        raise DeliveryError(
            "Pull-request traceability mutation was not read-after-write verified."
        )
    return {
        "status": "verified",
        "operation": mutation.operation,
        "work_item_id": work_item_id,
        "pull_request": {
            "number": pull_request.number,
            "url": pull_request.url,
            "head": pull_request.head,
            "base": pull_request.base,
            "state": pull_request.state,
            "merged": pull_request.merged,
            "mergeable": pull_request.mergeable,
            "mergeable_state": pull_request.mergeable_state,
            "draft": pull_request.draft,
        },
        "traceability_verified": trace.verified,
    }


def sync_merged_pull_request(
    provider: PullRequestProvider,
    work_item_provider: WorkItemProvider,
    work_item_id: str,
    pull_request_number: int,
    *,
    integration_branch: str,
    expected_head: str,
) -> dict[str, Any]:
    """Advance review to integration only after a verified merge into the target."""
    _validate_base_branch(integration_branch)
    _validate_task_branch(expected_head)
    item = work_item_provider.get(work_item_id)
    if item.state != LifecycleState.REVIEW:
        raise DeliveryError(
            "Merged pull-request synchronization requires a work item in review state; "
            f"got {item.state.value}."
        )

    pull_request = provider.get(pull_request_number)
    if pull_request.head != expected_head:
        raise DeliveryError("Pull request head does not match the expected Aegis task branch.")
    if pull_request.base != integration_branch:
        raise DeliveryError("Pull request base does not match the configured integration branch.")
    if not pull_request.merged or pull_request.state != "closed":
        return {
            "status": "not-merged",
            "work_item_id": work_item_id,
            "pull_request": {
                "number": pull_request.number,
                "url": pull_request.url,
                "state": pull_request.state,
                "merged": pull_request.merged,
                "mergeable": pull_request.mergeable,
                "mergeable_state": pull_request.mergeable_state,
            },
        }

    mutation = work_item_provider.transition(
        work_item_id,
        LifecycleState.INTEGRATION,
        expected_state=LifecycleState.REVIEW,
    )
    if not mutation.verified:
        raise DeliveryError(
            "Lifecycle transition mutation was not read-after-write verified."
        )
    return {
        "status": "verified",
        "work_item_id": work_item_id,
        "pull_request": {
            "number": pull_request.number,
            "url": pull_request.url,
            "head": pull_request.head,
            "base": pull_request.base,
            "state": pull_request.state,
            "merged": pull_request.merged,
            "mergeable": pull_request.mergeable,
            "mergeable_state": pull_request.mergeable_state,
        },
        "work_item": {
            "state_after": LifecycleState.INTEGRATION.value,
            "verified": mutation.verified,
        },
    }


def _build_provider(repository: str, token_env: str) -> GitHubPullRequestProvider:
    token = os.environ.get(token_env, "")
    return GitHubPullRequestProvider(repository, token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage the Aegis pull-request delivery lifecycle."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("repository")
    create.add_argument("work_item_id")
    create.add_argument("head")
    create.add_argument("base")
    create.add_argument("title")
    create.add_argument("--body", default="")
    create.add_argument("--draft", action="store_true")
    create.add_argument("--token-env", default="GITHUB_TOKEN")

    sync = subparsers.add_parser("sync-merge")
    sync.add_argument("repository")
    sync.add_argument("work_item_id")
    sync.add_argument("pull_request_number", type=int)
    sync.add_argument("expected_head")
    sync.add_argument("integration_branch")
    sync.add_argument("--token-env", default="GITHUB_TOKEN")

    args = parser.parse_args()

    try:
        provider = _build_provider(args.repository, args.token_env)
        work_item_provider = GitHubIssuesProvider(
            args.repository,
            os.environ.get(args.token_env, ""),
        )
        if args.command == "create":
            result = create_review_pull_request(
                provider,
                work_item_provider,
                args.work_item_id,
                CreatePullRequestRequest(
                    repository=args.repository,
                    head=args.head,
                    base=args.base,
                    title=args.title,
                    body=args.body,
                    draft=args.draft,
                ),
            )
        else:
            result = sync_merged_pull_request(
                provider,
                work_item_provider,
                args.work_item_id,
                args.pull_request_number,
                integration_branch=args.integration_branch,
                expected_head=args.expected_head,
            )
    except (DeliveryError, WorkItemLifecycleError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
