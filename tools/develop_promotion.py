#!/usr/bin/env python3
"""Prepare an owner-gated direct pull request from ai/integration to develop."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from github_http_security import (
    github_api_headers,
    parse_github_json,
    read_bounded_response,
    validate_github_api_base_url,
)
from promotion_readiness import (
    DEFAULT_API_BASE_URL,
    DEFAULT_SOURCE_BRANCH,
    DEFAULT_WORKFLOW,
    GitHubPromotionProvider,
    PromotionReadiness,
    PromotionReadinessError,
)

TARGET_BRANCH = "develop"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORK_ITEM_RE = re.compile(r"^[1-9][0-9]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HTTPS_URL_RE = re.compile(r"^https://[^\s]+$")
VERIFIED_SOURCE_RE = re.compile(
    r"(?m)^- Verified source SHA: (?P<sha>[0-9a-f]{40})$"
)


class DevelopPromotionError(RuntimeError):
    """Raised when a develop promotion cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class DevelopPromotionRequest:
    repository: str
    work_item_id: str
    owner_verified_source_sha: str
    source_branch: str = DEFAULT_SOURCE_BRANCH
    target_branch: str = TARGET_BRANCH
    workflow: str = DEFAULT_WORKFLOW
    draft: bool = True


@dataclass(frozen=True, slots=True)
class DevelopPromotionPullRequest:
    number: int
    url: str
    state: str
    merged: bool
    head: str
    head_sha: str
    base: str
    draft: bool
    body: str


@dataclass(frozen=True, slots=True)
class DevelopPromotionResult:
    repository: str
    work_item_id: str
    source_sha: str
    target_sha: str
    pull_request: DevelopPromotionPullRequest
    pull_request_reused: bool


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API calls from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise DevelopPromotionError("GitHub API returned an unexpected redirect.")


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
        raise DevelopPromotionError("Unable to communicate with GitHub API.") from exc


class DevelopPromotionProvider(Protocol):
    repository: str

    def assess_readiness(
        self,
        *,
        source_branch: str,
        target_branch: str,
        workflow: str,
        expected_source_sha: str,
    ) -> PromotionReadiness: ...

    def list_open_pull_requests(
        self,
        *,
        head: str,
        base: str,
    ) -> list[DevelopPromotionPullRequest]: ...

    def get_pull_request(self, number: int) -> DevelopPromotionPullRequest: ...

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool,
    ) -> DevelopPromotionPullRequest: ...


class GitHubDevelopPromotionProvider:
    """GitHub implementation of the owner-gated develop promotion boundary."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise DevelopPromotionError("Repository must use owner/name format.")
        if not token.strip():
            raise DevelopPromotionError("GitHub API token must not be empty.")
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise DevelopPromotionError(str(exc)) from exc
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
            raise DevelopPromotionError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            payload,
        )

    def assess_readiness(
        self,
        *,
        source_branch: str,
        target_branch: str,
        workflow: str,
        expected_source_sha: str,
    ) -> PromotionReadiness:
        return GitHubPromotionProvider(
            self.repository,
            self._token,
            transport=self._transport,
            api_base_url=self._api_base_url,
        ).assess(
            source_branch=source_branch,
            target_branch=target_branch,
            workflow=workflow,
            expected_source_sha=expected_source_sha,
        )

    @staticmethod
    def _parse_pull_request(
        data: Mapping[str, Any],
    ) -> DevelopPromotionPullRequest | None:
        number = data.get("number")
        url = data.get("html_url")
        state = data.get("state")
        merged_at = data.get("merged_at")
        head = data.get("head")
        base = data.get("base")
        draft = data.get("draft", False)
        body = data.get("body") or ""
        head_ref = head.get("ref") if isinstance(head, Mapping) else None
        head_sha = head.get("sha") if isinstance(head, Mapping) else None
        base_ref = base.get("ref") if isinstance(base, Mapping) else None
        if not (
            isinstance(number, int)
            and number > 0
            and isinstance(url, str)
            and HTTPS_URL_RE.fullmatch(url)
            and isinstance(state, str)
            and state in {"open", "closed"}
            and isinstance(merged_at, (str, type(None)))
            and isinstance(head_ref, str)
            and isinstance(head_sha, str)
            and SHA_RE.fullmatch(head_sha)
            and isinstance(base_ref, str)
            and isinstance(draft, bool)
            and isinstance(body, str)
        ):
            return None
        return DevelopPromotionPullRequest(
            number=number,
            url=url,
            state=state,
            merged=merged_at is not None,
            head=head_ref,
            head_sha=head_sha,
            base=base_ref,
            draft=draft,
            body=body,
        )

    def list_open_pull_requests(
        self,
        *,
        head: str,
        base: str,
    ) -> list[DevelopPromotionPullRequest]:
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
            raise DevelopPromotionError(
                f"Unable to list develop promotion pull requests; HTTP {status}."
            )
        result: list[DevelopPromotionPullRequest] = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            parsed = self._parse_pull_request(item)
            if parsed is not None and parsed.head == head and parsed.base == base:
                result.append(parsed)
        return result

    def get_pull_request(self, number: int) -> DevelopPromotionPullRequest:
        if number <= 0:
            raise DevelopPromotionError("Pull-request number must be positive.")
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/pulls/{number}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise DevelopPromotionError(
                f"Unable to read develop promotion pull request #{number}; HTTP {status}."
            )
        parsed = self._parse_pull_request(data)
        if parsed is None:
            raise DevelopPromotionError(
                "GitHub develop promotion pull-request response is malformed."
            )
        return parsed

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool,
    ) -> DevelopPromotionPullRequest:
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
            raise DevelopPromotionError(
                f"Unable to create develop promotion pull request; HTTP {status}."
            )
        number = data.get("number")
        if not isinstance(number, int):
            raise DevelopPromotionError(
                "Develop promotion pull-request creation returned no number."
            )
        return self.get_pull_request(number)


def _validate_request(request: DevelopPromotionRequest) -> None:
    if not REPOSITORY_RE.fullmatch(request.repository):
        raise DevelopPromotionError("Repository must use owner/name format.")
    if not WORK_ITEM_RE.fullmatch(request.work_item_id):
        raise DevelopPromotionError("Work-item id must be a positive integer.")
    if request.source_branch != DEFAULT_SOURCE_BRANCH:
        raise DevelopPromotionError("Develop promotion source must be ai/integration.")
    if request.target_branch != TARGET_BRANCH:
        raise DevelopPromotionError("Develop promotion target must be develop.")
    if not SHA_RE.fullmatch(request.owner_verified_source_sha):
        raise DevelopPromotionError("Owner-verified source SHA is malformed.")


def _promotion_body(
    request: DevelopPromotionRequest,
    readiness: PromotionReadiness,
) -> str:
    validation = readiness.validation
    validation_line = (
        f"- Aegis Validation: run {validation.id} at {validation.validated_sha} "
        f"({validation.url})"
        if validation is not None
        else "- Aegis Validation: unavailable"
    )
    return (
        "## Aegis owner-gated develop promotion\n\n"
        f"- Work item: #{request.work_item_id}\n"
        f"- Source: {request.source_branch}\n"
        f"- Verified source SHA: {readiness.source.sha}\n"
        f"- Target: {request.target_branch} at {readiness.target.sha}\n"
        f"{validation_line}\n\n"
        "Owner verification is an explicit human checkpoint. "
        "The supplied verified source SHA was checked against the current protected "
        "ai/integration state before this pull request was created. "
        "Do not merge this pull request if ai/integration has advanced beyond the "
        "verified SHA; a fresh owner verification is required."
    )


def _verify_pull_request(
    pull_request: DevelopPromotionPullRequest,
    request: DevelopPromotionRequest,
) -> None:
    match = VERIFIED_SOURCE_RE.search(pull_request.body)
    if (
        pull_request.state != "open"
        or pull_request.merged
        or pull_request.head != request.source_branch
        or pull_request.base != request.target_branch
        or pull_request.head_sha != request.owner_verified_source_sha
        or match is None
        or match.group("sha") != request.owner_verified_source_sha
    ):
        raise DevelopPromotionError(
            "Develop promotion pull request verification failed or the owner-verified "
            "source SHA is stale."
        )


def prepare_develop_promotion(
    provider: DevelopPromotionProvider,
    request: DevelopPromotionRequest,
) -> DevelopPromotionResult:
    """Create or reuse a direct develop PR for an explicitly supplied verified SHA."""
    _validate_request(request)
    readiness = provider.assess_readiness(
        source_branch=request.source_branch,
        target_branch=request.target_branch,
        workflow=request.workflow,
        expected_source_sha=request.owner_verified_source_sha,
    )
    if not readiness.ready:
        raise DevelopPromotionError(
            "Promotion readiness is blocked: " + "; ".join(readiness.blockers)
        )

    existing = provider.list_open_pull_requests(
        head=request.source_branch,
        base=request.target_branch,
    )
    if len(existing) > 1:
        raise DevelopPromotionError(
            "Multiple open develop promotion pull requests exist for ai/integration -> develop."
        )

    reused = bool(existing)
    if existing:
        pull_request = provider.get_pull_request(existing[0].number)
    else:
        pull_request = provider.create_pull_request(
            title=(
                "chore: promote owner-verified ai/integration to develop "
                f"(#{request.work_item_id})"
            ),
            body=_promotion_body(request, readiness),
            head=request.source_branch,
            base=request.target_branch,
            draft=request.draft,
        )

    _verify_pull_request(pull_request, request)
    return DevelopPromotionResult(
        repository=request.repository,
        work_item_id=request.work_item_id,
        source_sha=readiness.source.sha,
        target_sha=readiness.target.sha,
        pull_request=pull_request,
        pull_request_reused=reused,
    )


def _to_dict(result: DevelopPromotionResult) -> dict[str, Any]:
    return {
        "status": "prepared",
        "repository": result.repository,
        "work_item_id": result.work_item_id,
        "source_sha": result.source_sha,
        "target_sha": result.target_sha,
        "pull_request_reused": result.pull_request_reused,
        "pull_request": {
            "number": result.pull_request.number,
            "url": result.pull_request.url,
            "state": result.pull_request.state,
            "merged": result.pull_request.merged,
            "head": result.pull_request.head,
            "head_sha": result.pull_request.head_sha,
            "base": result.pull_request.base,
            "draft": result.pull_request.draft,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare an owner-gated direct ai/integration -> develop pull request."
    )
    parser.add_argument("repository")
    parser.add_argument("work_item_id")
    parser.add_argument("--owner-verified-source-sha", required=True)
    parser.add_argument("--source", default=DEFAULT_SOURCE_BRANCH)
    parser.add_argument("--target", default=TARGET_BRANCH)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument(
        "--ready",
        action="store_true",
        help="Create the develop pull request as ready for review.",
    )
    args = parser.parse_args()

    try:
        token = os.environ.get(args.token_env, "")
        provider = GitHubDevelopPromotionProvider(args.repository, token)
        result = prepare_develop_promotion(
            provider,
            DevelopPromotionRequest(
                repository=args.repository,
                work_item_id=args.work_item_id,
                owner_verified_source_sha=args.owner_verified_source_sha,
                source_branch=args.source,
                target_branch=args.target,
                workflow=args.workflow,
                draft=not args.ready,
            ),
        )
    except (DevelopPromotionError, PromotionReadinessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    print(json.dumps(_to_dict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
