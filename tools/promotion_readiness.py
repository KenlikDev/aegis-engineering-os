#!/usr/bin/env python3
"""Verify whether ai/integration is ready for owner-controlled promotion."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

GITHUB_API_VERSION = "2026-03-10"
DEFAULT_API_BASE_URL = "https://api.github.com"
DEFAULT_SOURCE_BRANCH = "ai/integration"
DEFAULT_WORKFLOW = ".github/workflows/validate.yml"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SOURCE_RE = re.compile(r"^ai/integration$")
TARGETS = frozenset({"develop", "main"})
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PromotionReadinessError(RuntimeError):
    """Raised when promotion readiness cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class BranchSnapshot:
    branch: str
    sha: str
    protected: bool


@dataclass(frozen=True, slots=True)
class CompareSnapshot:
    status: str
    ahead_by: int
    behind_by: int
    total_commits: int
    changed_files_reported: int
    changed_files_complete: bool


@dataclass(frozen=True, slots=True)
class ValidationRun:
    id: int
    workflow: str
    status: str
    conclusion: str | None
    head_sha: str
    url: str
    evidence_type: str = "branch-push"
    validated_sha: str | None = None
    pull_request_number: int | None = None


@dataclass(frozen=True, slots=True)
class PromotionReadiness:
    """Observed promotion readiness for one source/target pair."""

    repository: str
    source: BranchSnapshot
    target: BranchSnapshot
    compare: CompareSnapshot
    validation: ValidationRun | None
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API calls from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise PromotionReadinessError("GitHub API returned an unexpected redirect.")


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

    try:
        with _HTTP_OPENER.open(
            Request(url, data=body, headers=dict(request_headers), method=method),
            timeout=30.0,
        ) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        return exc.code, data
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionReadinessError(
            "Unable to communicate with GitHub API."
        ) from exc


class GitHubPromotionProvider:
    """Read-only GitHub state needed for promotion readiness."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise PromotionReadinessError("Repository must use owner/name format.")
        if not token.strip():
            raise PromotionReadinessError("GitHub API token must not be empty.")
        parsed = urlparse(api_base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise PromotionReadinessError(
                "GitHub API base URL must be an HTTPS service root."
            )
        self.repository = repository
        self._token = token
        self._transport = transport or _default_transport
        self._api_base_url = api_base_url.rstrip("/")

    def _request(self, method: str, path: str) -> tuple[int, Any]:
        if not path.startswith("/"):
            raise PromotionReadinessError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            None,
        )

    def get_branch(self, branch: str) -> BranchSnapshot:
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/branches/{quote(branch, safe='')}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionReadinessError(
                f"Unable to read branch {branch!r}; HTTP {status}."
            )
        commit = data.get("commit")
        sha = commit.get("sha") if isinstance(commit, Mapping) else None
        if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
            raise PromotionReadinessError(
                f"GitHub branch {branch!r} did not return a valid commit SHA."
            )
        protected = data.get("protected")
        return BranchSnapshot(
            branch=branch,
            sha=sha,
            protected=protected is True,
        )

    def compare(self, base_sha: str, head_sha: str) -> CompareSnapshot:
        for label, sha in (("base", base_sha), ("head", head_sha)):
            if not SHA_RE.fullmatch(sha):
                raise PromotionReadinessError(
                    f"{label} commit SHA is malformed."
                )
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/compare/{base_sha}...{head_sha}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionReadinessError(
                f"Unable to compare promotion refs; HTTP {status}."
            )
        fields = ("status", "ahead_by", "behind_by", "total_commits")
        if not isinstance(data.get("status"), str) or any(
            not isinstance(data.get(field), int) for field in fields[1:]
        ):
            raise PromotionReadinessError("GitHub compare response is malformed.")
        files = data.get("files", [])
        if not isinstance(files, list):
            raise PromotionReadinessError("GitHub compare files response is malformed.")
        changed_files_reported = len(files)
        return CompareSnapshot(
            status=data["status"],
            ahead_by=data["ahead_by"],
            behind_by=data["behind_by"],
            total_commits=data["total_commits"],
            changed_files_reported=changed_files_reported,
            changed_files_complete=changed_files_reported < 300,
        )

    def _workflow_runs(
        self,
        workflow: str,
        *,
        head_sha: str | None = None,
    ) -> list[Mapping[str, Any]]:
        if not workflow.strip():
            raise PromotionReadinessError("Validation workflow must not be empty.")
        if head_sha is not None and not SHA_RE.fullmatch(head_sha):
            raise PromotionReadinessError("Validation head SHA is malformed.")
        parameters = {"per_page": "20"}
        if head_sha is not None:
            parameters["head_sha"] = head_sha
        query = urlencode(parameters)
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/actions/workflows/{quote(workflow, safe='')}/runs?{query}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise PromotionReadinessError(
                f"Unable to read validation workflow runs; HTTP {status}."
            )
        runs = data.get("workflow_runs")
        if not isinstance(runs, list):
            raise PromotionReadinessError(
                "GitHub workflow-run response is malformed."
            )
        return [item for item in runs if isinstance(item, Mapping)]

    @staticmethod
    def _parse_successful_run(
        workflow: str,
        item: Mapping[str, Any],
        *,
        validated_sha: str,
        evidence_type: str,
        expected_head_sha: str | None = None,
        pull_request_number: int | None = None,
    ) -> ValidationRun | None:
        run_id = item.get("id")
        run_status = item.get("status")
        conclusion = item.get("conclusion")
        run_sha = item.get("head_sha")
        run_url = item.get("html_url")
        run_name = item.get("name")
        if not (
            isinstance(run_id, int)
            and isinstance(run_status, str)
            and isinstance(conclusion, str)
            and isinstance(run_sha, str)
            and SHA_RE.fullmatch(run_sha)
            and isinstance(run_url, str)
            and isinstance(run_name, str)
            and run_status == "completed"
            and conclusion == "success"
            and run_name == "Aegis Validation"
            and (
                expected_head_sha is None
                or run_sha == expected_head_sha
            )
        ):
            return None
        return ValidationRun(
            id=run_id,
            workflow=workflow,
            status=run_status,
            conclusion=conclusion,
            head_sha=run_sha,
            url=run_url,
            evidence_type=evidence_type,
            validated_sha=validated_sha,
            pull_request_number=pull_request_number,
        )

    def _get_pull_request(
        self,
        number: int,
    ) -> Mapping[str, Any] | None:
        if number <= 0:
            raise PromotionReadinessError("Pull-request number must be positive.")
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/pulls/{number}",
        )
        if status != 200 or not isinstance(data, Mapping):
            return None
        return data

    def _list_closed_pull_requests(
        self,
        *,
        head_branch: str,
        base_branch: str,
    ) -> list[Mapping[str, Any]]:
        if not head_branch or not base_branch:
            return []
        owner = self.repository.split("/", 1)[0]
        query = urlencode(
            {
                "state": "closed",
                "head": f"{owner}:{head_branch}",
                "base": base_branch,
                "per_page": "20",
            }
        )
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/pulls?{query}",
        )
        if status != 200 or not isinstance(data, list):
            raise PromotionReadinessError(
                f"Unable to read closed pull requests; HTTP {status}."
            )
        return [item for item in data if isinstance(item, Mapping)]

    def _latest_successful_merged_pr_validation(
        self,
        workflow: str,
        merge_commit_sha: str,
    ) -> ValidationRun | None:
        for item in self._workflow_runs(workflow):
            if item.get("event") != "pull_request":
                continue
            if item.get("path") not in {None, workflow}:
                continue

            successful = self._parse_successful_run(
                workflow,
                item,
                validated_sha=merge_commit_sha,
                evidence_type="merged-pull-request",
            )
            if successful is None:
                continue

            head_branch = item.get("head_branch")
            if not isinstance(head_branch, str) or not head_branch:
                continue

            run_head_sha = item.get("head_sha")
            if not isinstance(run_head_sha, str) or not SHA_RE.fullmatch(run_head_sha):
                continue

            candidates = self._list_closed_pull_requests(
                head_branch=head_branch,
                base_branch=DEFAULT_SOURCE_BRANCH,
            )
            matching_prs: list[tuple[int, Mapping[str, Any]]] = []
            for candidate in candidates:
                number = candidate.get("number")
                if not isinstance(number, int) or number <= 0:
                    continue
                pull_request = self._get_pull_request(number)
                if pull_request is None:
                    continue

                head_data = pull_request.get("head")
                base_data = pull_request.get("base")
                head_ref = head_data.get("ref") if isinstance(head_data, Mapping) else None
                head_sha = head_data.get("sha") if isinstance(head_data, Mapping) else None
                base_ref = base_data.get("ref") if isinstance(base_data, Mapping) else None
                state = pull_request.get("state")
                merged_at = pull_request.get("merged_at")
                pr_merge_sha = pull_request.get("merge_commit_sha")

                if (
                    state == "closed"
                    and isinstance(merged_at, str)
                    and head_ref == head_branch
                    and head_sha == run_head_sha
                    and base_ref == DEFAULT_SOURCE_BRANCH
                    and pr_merge_sha == merge_commit_sha
                ):
                    matching_prs.append((number, pull_request))

            if len(matching_prs) == 1:
                number, _ = matching_prs[0]
                return ValidationRun(
                    id=successful.id,
                    workflow=successful.workflow,
                    status=successful.status,
                    conclusion=successful.conclusion,
                    head_sha=successful.head_sha,
                    url=successful.url,
                    evidence_type="merged-pull-request",
                    validated_sha=merge_commit_sha,
                    pull_request_number=number,
                )
            if len(matching_prs) > 1:
                raise PromotionReadinessError(
                    "Multiple merged pull requests match one successful validation run."
                )
        return None

    def latest_successful_validation(
        self,
        workflow: str,
        head_sha: str,
    ) -> ValidationRun | None:
        if not SHA_RE.fullmatch(head_sha):
            raise PromotionReadinessError("Validation head SHA is malformed.")

        candidates: list[ValidationRun] = []
        for item in self._workflow_runs(workflow, head_sha=head_sha):
            parsed = self._parse_successful_run(
                workflow,
                item,
                validated_sha=head_sha,
                evidence_type="branch-push",
                expected_head_sha=head_sha,
            )
            if parsed is not None:
                candidates.append(parsed)

        if candidates:
            candidates.sort(key=lambda run: run.id, reverse=True)
            return candidates[0]

        return self._latest_successful_merged_pr_validation(
            workflow,
            head_sha,
        )

    def assess(
        self,
        *,
        source_branch: str,
        target_branch: str,
        workflow: str,
        expected_source_sha: str | None = None,
        expected_target_sha: str | None = None,
    ) -> PromotionReadiness:
        if source_branch != DEFAULT_SOURCE_BRANCH or not SOURCE_RE.fullmatch(source_branch):
            raise PromotionReadinessError(
                "Promotion source must be ai/integration."
            )
        if target_branch not in TARGETS:
            raise PromotionReadinessError(
                "Promotion target must be develop or main."
            )
        for name, sha in (
            ("expected_source_sha", expected_source_sha),
            ("expected_target_sha", expected_target_sha),
        ):
            if sha is not None and not SHA_RE.fullmatch(sha):
                raise PromotionReadinessError(f"{name} is malformed.")

        source = self.get_branch(source_branch)
        target = self.get_branch(target_branch)
        blockers: list[str] = []

        if not source.protected:
            blockers.append("ai/integration must remain protected.")
        if not target.protected:
            blockers.append(f"{target_branch} must remain protected.")
        if expected_source_sha is not None and source.sha != expected_source_sha:
            blockers.append("ai/integration changed since the promotion snapshot.")
        if expected_target_sha is not None and target.sha != expected_target_sha:
            blockers.append(f"{target_branch} changed since the promotion snapshot.")

        comparison = self.compare(target.sha, source.sha)
        if comparison.behind_by != 0:
            blockers.append(
                f"ai/integration is behind {target_branch} by {comparison.behind_by} commit(s)."
            )
        if comparison.ahead_by == 0:
            blockers.append("Promotion contains no commits beyond the target branch.")
        validation = self.latest_successful_validation(workflow, source.sha)
        if validation is None:
            blockers.append(
                "No successful Aegis Validation run exists for the exact ai/integration SHA."
            )

        return PromotionReadiness(
            repository=self.repository,
            source=source,
            target=target,
            compare=comparison,
            validation=validation,
            blockers=tuple(blockers),
        )


def _to_dict(result: PromotionReadiness) -> dict[str, Any]:
    return {
        "status": "ready" if result.ready else "blocked",
        "repository": result.repository,
        "source": {
            "branch": result.source.branch,
            "sha": result.source.sha,
            "protected": result.source.protected,
        },
        "target": {
            "branch": result.target.branch,
            "sha": result.target.sha,
            "protected": result.target.protected,
        },
        "compare": {
            "status": result.compare.status,
            "ahead_by": result.compare.ahead_by,
            "behind_by": result.compare.behind_by,
            "total_commits": result.compare.total_commits,
            "changed_files_reported": result.compare.changed_files_reported,
            "changed_files_complete": result.compare.changed_files_complete,
        },
        "validation": (
            {
                "id": result.validation.id,
                "workflow": result.validation.workflow,
                "status": result.validation.status,
                "conclusion": result.validation.conclusion,
                "head_sha": result.validation.head_sha,
                "validated_sha": result.validation.validated_sha,
                "evidence_type": result.validation.evidence_type,
                "pull_request_number": result.validation.pull_request_number,
                "url": result.validation.url,
            }
            if result.validation
            else None
        ),
        "blockers": list(result.blockers),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify whether ai/integration is ready for promotion."
    )
    parser.add_argument("repository")
    parser.add_argument("target", choices=sorted(TARGETS))
    parser.add_argument("--source", default=DEFAULT_SOURCE_BRANCH)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--expected-target-sha")
    parser.add_argument("--evidence-output", type=os.path.abspath)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()

    try:
        observed_at = datetime.now(timezone.utc)
        token = os.environ.get(args.token_env, "")
        provider = GitHubPromotionProvider(args.repository, token)
        result = provider.assess(
            source_branch=args.source,
            target_branch=args.target,
            workflow=args.workflow,
            expected_source_sha=args.expected_source_sha,
            expected_target_sha=args.expected_target_sha,
        )
    except (PromotionReadinessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    if args.evidence_output:
        from evidence_adapters import promotion_readiness_evidence
        from evidence_contract import write_evidence

        write_evidence(
            promotion_readiness_evidence(result, observed_at=observed_at),
            args.evidence_output,
        )

    print(json.dumps(_to_dict(result), indent=2, sort_keys=True))
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
