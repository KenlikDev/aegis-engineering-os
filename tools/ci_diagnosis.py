#!/usr/bin/env python3
"""Diagnose GitHub Actions failures without mutating CI state."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
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

from evidence_contract import EvidenceContractError

DEFAULT_API_BASE_URL = "https://api.github.com"
DEFAULT_LOG_LIMIT = 8000
MAX_LOG_DOWNLOAD_BYTES = 1024 * 1024
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
TOKEN_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9_]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"gho_[A-Za-z0-9_]+"),
    re.compile(r"ghu_[A-Za-z0-9_]+"),
    re.compile(r"ghs_[A-Za-z0-9_]+"),
    re.compile(r"ghr_[A-Za-z0-9_]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
)
SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|credential)",
    re.IGNORECASE,
)


class CIDiagnosisError(RuntimeError):
    """Raised when CI diagnosis cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class WorkflowRunSnapshot:
    repository: str
    run_id: int
    name: str
    workflow_path: str
    event: str
    status: str
    conclusion: str | None
    head_branch: str | None
    head_sha: str
    url: str


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: int
    name: str
    status: str
    conclusion: str | None
    url: str
    failed_steps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    category: str
    severity: str
    actionable: bool
    job_id: int
    job: str
    step: str | None
    message: str
    evidence: str


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    run: WorkflowRunSnapshot
    jobs: tuple[JobSnapshot, ...]
    findings: tuple[DiagnosticFinding, ...]
    status: str

    @property
    def actionable(self) -> bool:
        return any(finding.actionable for finding in self.findings)


class CIDiagnosisProvider(Protocol):
    """Provider-neutral read-only CI diagnosis contract."""

    repository: str

    def get_run(self, run_id: int) -> WorkflowRunSnapshot:
        ...

    def latest_run(self, workflow: str, branch: str | None = None) -> WorkflowRunSnapshot:
        ...

    def list_jobs(self, run_id: int) -> list[JobSnapshot]:
        ...

    def get_job_log(self, job_id: int) -> str:
        ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API calls from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise CIDiagnosisError("GitHub API returned an unexpected redirect.")


_HTTP_OPENER = build_opener(_NoRedirectHandler())

class _LogRedirectHandler(HTTPRedirectHandler):
    """Follow job-log redirects without forwarding GitHub credentials."""

    def redirect_request(
        self,
        request: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request:
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or not parsed.netloc:
            raise CIDiagnosisError("CI log redirect must target an HTTPS URL.")
        return Request(newurl, headers={"Accept": "text/plain"}, method="GET")


_LOG_HTTP_OPENER = build_opener(_LogRedirectHandler())


def _read_bounded_response(response: Any, *, limit: int = MAX_LOG_DOWNLOAD_BYTES) -> bytes:
    """Read a CI job-log response without allowing unbounded memory growth."""
    if limit <= 0:
        raise CIDiagnosisError("CI log download limit must be positive.")

    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise CIDiagnosisError(
            f"CI job log exceeds the {limit}-byte download limit."
        )
    return raw


def _redact(value: str) -> str:
    """Redact credential-like material before it becomes diagnostic evidence."""
    result = value
    for pattern in TOKEN_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    lines: list[str] = []
    for line in result.splitlines():
        if SECRET_KEY_RE.search(line) and ":" in line:
            key, _separator, _secret = line.partition(":")
            if key.strip():
                lines.append(f"{key}: [REDACTED]")
                continue
        lines.append(line)
    return "\n".join(lines)


def _bounded_excerpt(log: str, *, limit: int = DEFAULT_LOG_LIMIT) -> str:
    if limit <= 0:
        raise CIDiagnosisError("Log limit must be positive.")
    safe_log = _redact(log)
    if len(safe_log) <= limit:
        return safe_log
    return safe_log[-limit:]


def _require_run_id(value: int) -> int:
    if value <= 0:
        raise CIDiagnosisError("Workflow run id must be positive.")
    return value


def _classify_failure(
    *,
    job: JobSnapshot,
    step_name: str | None,
    log: str,
) -> DiagnosticFinding:
    text = f"{step_name or ''}\n{log}".lower()

    normalized_step = (step_name or "").strip().lower()
    step_categories = {
        "run security review": (
            "security-review",
            "high",
            True,
            "The failed step is the Aegis security review.",
        ),
        "run policy tests": (
            "test-failure",
            "medium",
            True,
            "The failed step is the Aegis policy test suite.",
        ),
        "validate repository structure": (
            "repository-structure",
            "high",
            True,
            "The failed step is the repository structural validation.",
        ),
        "exercise project bootstrap": (
            "bootstrap-failure",
            "high",
            True,
            "The failed step is the project bootstrap verification.",
        ),
        "compile aegis tools": (
            "source-syntax",
            "high",
            True,
            "The failed step is Python tool compilation.",
        ),
    }
    direct = step_categories.get(normalized_step)
    if direct is not None:
        category, severity, actionable, message = direct
        return DiagnosticFinding(
            category=category,
            severity=severity,
            actionable=actionable,
            job_id=job.job_id,
            job=job.name,
            step=step_name,
            message=message,
            evidence=f"Failed step: {step_name}.\n{_bounded_excerpt(log)}",
        )

    rules = (
        (
            "ci-permission",
            "high",
            True,
            ("resource not accessible by integration", "permission denied", "forbidden"),
            "The observed CI output contains a permission or authorization failure.",
        ),
        (
            "timeout",
            "high",
            True,
            ("timed out", "timeout", "time limit exceeded"),
            "The observed CI output indicates a timeout.",
        ),
        (
            "security-review",
            "high",
            True,
            ("run security review", "security review", "security_review.py"),
            "The failing step is associated with the security review workflow.",
        ),
        (
            "repository-structure",
            "high",
            True,
            ("validate_aegis.py", "structural validation", "missing required files"),
            "The repository structural validation failed.",
        ),
        (
            "source-syntax",
            "high",
            True,
            ("py_compile", "syntaxerror", "indentationerror"),
            "The failing evidence indicates a Python source syntax error.",
        ),
        (
            "test-failure",
            "medium",
            True,
            ("run policy tests", "unittest", "failed (failures=", "traceback (most recent call last)"),
            "The observed CI output indicates a test failure.",
        ),
        (
            "bootstrap-failure",
            "high",
            True,
            ("exercise project bootstrap", "bootstrap_project.py", "bootstrap failed"),
            "The project bootstrap verification failed.",
        ),
    )

    for category, severity, actionable, markers, message in rules:
        matched = next((marker for marker in markers if marker in text), None)
        if matched is not None:
            evidence = _bounded_excerpt(log)
            return DiagnosticFinding(
                category=category,
                severity=severity,
                actionable=actionable,
                job_id=job.job_id,
                job=job.name,
                step=step_name,
                message=message,
                evidence=f"Matched evidence marker: {matched}.\\n{evidence}",
            )

    return DiagnosticFinding(
        category="unknown",
        severity="low",
        actionable=False,
        job_id=job.job_id,
        job=job.name,
        step=step_name,
        message="No supported deterministic failure signature was found in the observed evidence.",
        evidence=_bounded_excerpt(log),
    )


def diagnose(
    provider: CIDiagnosisProvider,
    run_id: int,
    *,
    log_limit: int = DEFAULT_LOG_LIMIT,
) -> DiagnosticReport:
    """Produce a read-only diagnosis for one workflow run."""
    _require_run_id(run_id)
    run = provider.get_run(run_id)
    if run.repository != provider.repository:
        raise CIDiagnosisError("Workflow run repository does not match the requested repository.")

    jobs = tuple(provider.list_jobs(run.run_id))
    findings: list[DiagnosticFinding] = []

    for job in jobs:
        if job.conclusion != "failure":
            continue
        log = _bounded_excerpt(provider.get_job_log(job.job_id), limit=log_limit)
        failed_steps = job.failed_steps or (job.name or None,)
        for step_name in failed_steps:
            findings.append(
                _classify_failure(
                    job=job,
                    step_name=step_name,
                    log=log,
                )
            )

    findings.sort(
        key=lambda finding: (
            {"high": 0, "medium": 1, "low": 2}[finding.severity],
            finding.job_id,
            finding.category,
        )
    )

    if run.conclusion == "success":
        status = "healthy"
    elif findings and any(finding.actionable for finding in findings):
        status = "diagnosed"
    else:
        status = "inconclusive"

    return DiagnosticReport(
        run=run,
        jobs=jobs,
        findings=tuple(findings),
        status=status,
    )


class GitHubCIDiagnosisProvider:
    """Read-only GitHub Actions provider."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: Callable[
            [str, str, Mapping[str, str], Mapping[str, Any] | None],
            tuple[int, Any],
        ]
        | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise CIDiagnosisError("Repository must use owner/name format.")
        if not token.strip():
            raise CIDiagnosisError("GitHub API token must not be empty.")
        if (
            not isinstance(api_base_url, str)
            or api_base_url != api_base_url.strip()
            or not api_base_url
        ):
            raise CIDiagnosisError(
                "GitHub API base URL must be exactly https://api.github.com."
            )
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise CIDiagnosisError(str(exc)) from exc
        self.repository = repository
        self._token = token
        self._transport = transport or self._default_transport
        self._api_base_url = normalized_api_base_url

    def _default_transport(
        self,
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
            raise CIDiagnosisError("Unable to communicate with GitHub API.") from exc

    def _request(self, method: str, path: str) -> tuple[int, Any]:
        if not path.startswith("/"):
            raise CIDiagnosisError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            None,
        )

    @staticmethod
    def _parse_run(repository: str, data: Mapping[str, Any]) -> WorkflowRunSnapshot:
        repository_data = data.get("repository")
        repository_name = (
            repository_data.get("full_name")
            if isinstance(repository_data, Mapping)
            else None
        )
        if repository_name != repository:
            raise CIDiagnosisError("Workflow run repository identity is invalid.")

        run_id = data.get("id")
        name = data.get("name")
        workflow_path = data.get("path")
        event = data.get("event")
        status = data.get("status")
        conclusion = data.get("conclusion")
        head_branch = data.get("head_branch")
        head_sha = data.get("head_sha")
        url = data.get("html_url")
        if not (
            isinstance(run_id, int)
            and run_id > 0
            and isinstance(name, str)
            and isinstance(workflow_path, str)
            and isinstance(event, str)
            and isinstance(status, str)
            and (conclusion is None or isinstance(conclusion, str))
            and (head_branch is None or isinstance(head_branch, str))
            and isinstance(head_sha, str)
            and re.fullmatch(r"[0-9a-f]{40}", head_sha)
            and isinstance(url, str)
        ):
            raise CIDiagnosisError("GitHub workflow-run response is malformed.")
        return WorkflowRunSnapshot(
            repository=repository,
            run_id=run_id,
            name=name,
            workflow_path=workflow_path,
            event=event,
            status=status,
            conclusion=conclusion,
            head_branch=head_branch,
            head_sha=head_sha,
            url=url,
        )

    def get_run(self, run_id: int) -> WorkflowRunSnapshot:
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/actions/runs/{_require_run_id(run_id)}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise CIDiagnosisError(f"Unable to read workflow run; HTTP {status}.")
        return self._parse_run(self.repository, data)

    def latest_run(
        self,
        workflow: str,
        branch: str | None = None,
    ) -> WorkflowRunSnapshot:
        if not workflow.strip():
            raise CIDiagnosisError("Workflow path must not be empty.")
        parameters = {"per_page": "20"}
        if branch:
            parameters["branch"] = branch
        query = urlencode(parameters)
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/actions/workflows/{quote(workflow, safe='')}/runs?{query}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise CIDiagnosisError(f"Unable to read workflow runs; HTTP {status}.")
        runs = data.get("workflow_runs")
        if not isinstance(runs, list) or not runs:
            raise CIDiagnosisError("No workflow runs matched the requested reference.")
        parsed = [
            self._parse_run(self.repository, item)
            for item in runs
            if isinstance(item, Mapping)
        ]
        parsed.sort(key=lambda item: item.run_id, reverse=True)
        return parsed[0]

    def list_jobs(self, run_id: int) -> list[JobSnapshot]:
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/actions/runs/{_require_run_id(run_id)}/jobs?per_page=100",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise CIDiagnosisError(f"Unable to read workflow jobs; HTTP {status}.")
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise CIDiagnosisError("GitHub workflow jobs response is malformed.")
        result: list[JobSnapshot] = []
        for item in jobs:
            if not isinstance(item, Mapping):
                continue
            job_id = item.get("id")
            name = item.get("name")
            job_status = item.get("status")
            conclusion = item.get("conclusion")
            url = item.get("html_url")
            raw_steps = item.get("steps", [])
            if not isinstance(raw_steps, list):
                raw_steps = []
            failed_steps = tuple(
                step.get("name")
                for step in raw_steps
                if isinstance(step, Mapping)
                and step.get("conclusion") == "failure"
                and isinstance(step.get("name"), str)
            )
            if (
                isinstance(job_id, int)
                and job_id > 0
                and isinstance(name, str)
                and isinstance(job_status, str)
                and (conclusion is None or isinstance(conclusion, str))
                and isinstance(url, str)
            ):
                result.append(
                    JobSnapshot(
                        job_id=job_id,
                        name=name,
                        status=job_status,
                        conclusion=conclusion,
                        url=url,
                        failed_steps=failed_steps,
                    )
                )
        result.sort(key=lambda job: job.job_id)
        return result

    def _download_job_log(self, job_id: int) -> str:
        if job_id <= 0:
            raise CIDiagnosisError("Workflow job id must be positive.")
        url = (
            f"{self._api_base_url}/repos/{self.repository}"
            f"/actions/jobs/{job_id}/logs"
        )
        request = Request(
            url,
            headers={
                **github_api_headers(),
                "Authorization": f"Bearer {self._token}",
            },
            method="GET",
        )
        try:
            with _LOG_HTTP_OPENER.open(request, timeout=30.0) as response:
                raw = _read_bounded_response(response)
                return raw.decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise CIDiagnosisError(
                f"Unable to read workflow job log; HTTP {exc.code}."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise CIDiagnosisError("Unable to download workflow job log.") from exc

    def get_job_log(self, job_id: int) -> str:
        """Return job logs through the credential-safe redirect downloader."""
        return self._download_job_log(job_id)



def _to_dict(report: DiagnosticReport) -> dict[str, Any]:
    return {
        "status": report.status,
        "run": asdict(report.run),
        "jobs": [asdict(job) for job in report.jobs],
        "findings": [asdict(finding) for finding in report.findings],
        "summary": {
            "actionable": sum(finding.actionable for finding in report.findings),
            "high": sum(finding.severity == "high" for finding in report.findings),
            "medium": sum(finding.severity == "medium" for finding in report.findings),
            "low": sum(finding.severity == "low" for finding in report.findings),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose one GitHub Actions run without changing CI state."
    )
    parser.add_argument("repository")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--run-id", type=int)
    selector.add_argument("--latest", action="store_true")
    parser.add_argument("--workflow", default=".github/workflows/validate.yml")
    parser.add_argument("--branch")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--log-limit", type=int, default=DEFAULT_LOG_LIMIT)
    parser.add_argument(
        "--canonical-evidence-output",
        type=Path,
        help="Optional canonical evidence-provenance output path.",
    )
    args = parser.parse_args()

    try:
        token = os.environ.get(args.token_env, "")
        provider = GitHubCIDiagnosisProvider(args.repository, token)
        if args.run_id is not None:
            run = provider.get_run(args.run_id)
        else:
            run = provider.latest_run(args.workflow, args.branch)
        report = diagnose(provider, run.run_id, log_limit=args.log_limit)

        if args.canonical_evidence_output is not None:
            from evidence_adapters import ci_diagnosis_evidence
            from evidence_contract import write_evidence

            write_evidence(
                ci_diagnosis_evidence(
                    report,
                    observed_at=datetime.now(timezone.utc),
                ),
                args.canonical_evidence_output,
            )
    except (CIDiagnosisError, EvidenceContractError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.status in {"healthy", "diagnosed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
