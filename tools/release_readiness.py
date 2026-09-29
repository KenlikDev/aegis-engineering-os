#!/usr/bin/env python3
"""Verify whether the protected main branch is ready for a release."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from evidence_contract import EvidenceContractError, parse_json_object

from github_http_security import (
    github_api_headers,
    read_bounded_response,
    validate_github_api_base_url,
)

from promotion_readiness import (
    DEFAULT_API_BASE_URL,
    DEFAULT_WORKFLOW,
    BranchSnapshot,
    GitHubPromotionProvider,
    ValidationRun,
)

RELEASE_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DEFAULT_TARGET_BRANCH = "main"
VERSION_PATH = "VERSION"
MANIFEST_PATH = "aegis-manifest.json"
REGISTRY_PATH = "skills/registry.json"
CHANGELOG_PATH = "CHANGELOG.md"


class ReleaseReadinessError(RuntimeError):
    """Raised when release readiness cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class ChangelogSnapshot:
    version_heading_present: bool
    version_section_has_content: bool
    unreleased_section_present: bool
    unreleased_content_present: bool


@dataclass(frozen=True, slots=True)
class ReleaseReadiness:
    """Observed release readiness for one protected release target."""

    repository: str
    target: BranchSnapshot
    validation: ValidationRun | None
    version: str | None
    manifest_version: str | None
    registry_version: str | None
    version_valid: bool
    changelog: ChangelogSnapshot
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers


class ReleaseReadinessProvider(Protocol):
    """Provider-neutral read-only contract for release readiness."""

    repository: str

    def get_branch(self, branch: str) -> BranchSnapshot: ...

    def latest_successful_validation(
        self,
        workflow: str,
        head_sha: str,
    ) -> ValidationRun | None: ...

    def get_file(self, path: str, ref: str) -> str: ...


JsonTransport = Callable[
    [str, str, Mapping[str, str]],
    tuple[int, Any],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API calls from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise ReleaseReadinessError("GitHub API returned an unexpected redirect.")


_HTTP_OPENER = build_opener(_NoRedirectHandler())


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
) -> tuple[int, Any]:
    request_headers = github_api_headers()
    request_headers.update(headers)
    try:
        with _HTTP_OPENER.open(
            Request(url, headers=dict(request_headers), method=method),
            timeout=30.0,
        ) as response:
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
        raise ReleaseReadinessError("Unable to communicate with GitHub API.") from exc


class GitHubReleaseReadinessProvider:
    """GitHub implementation of the release-readiness read boundary."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise ReleaseReadinessError("Repository must use owner/name format.")
        if not token.strip():
            raise ReleaseReadinessError("GitHub API token must not be empty.")
        if (
            not isinstance(api_base_url, str)
            or api_base_url != api_base_url.strip()
            or not api_base_url
        ):
            raise ReleaseReadinessError(
                "GitHub API base URL must be exactly https://api.github.com."
            )
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise ReleaseReadinessError(str(exc)) from exc
        self.repository = repository
        self._token = token
        self._transport = transport or _default_transport
        self._api_base_url = normalized_api_base_url
        self._github_promotion = GitHubPromotionProvider(
            repository,
            token,
            transport=self._promotion_transport,
            api_base_url=self._api_base_url,
        )

    def _promotion_transport(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None,
    ) -> tuple[int, Any]:
        if payload is not None:
            raise ReleaseReadinessError("Release readiness provider cannot write data.")
        return self._transport(method, url, headers)

    def get_branch(self, branch: str) -> BranchSnapshot:
        return self._github_promotion.get_branch(branch)

    def latest_successful_validation(
        self,
        workflow: str,
        head_sha: str,
    ) -> ValidationRun | None:
        return self._github_promotion.latest_successful_validation(workflow, head_sha)

    def get_file(self, path: str, ref: str) -> str:
        status, data = self._transport(
            "GET",
            (
                f"{self._api_base_url}/repos/{self.repository}/contents/"
                f"{quote(path, safe='/')}?ref={quote(ref, safe='')}"
            ),
            {
                **github_api_headers(),
                "Authorization": f"Bearer {self._token}",
            },
        )
        if status != 200 or not isinstance(data, Mapping):
            raise ReleaseReadinessError(
                f"Unable to read repository file {path!r}; HTTP {status}."
            )
        if data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
            raise ReleaseReadinessError(
                f"Repository file {path!r} did not return base64 content."
            )
        try:
            return base64.b64decode(data["content"], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseReadinessError(
                f"Repository file {path!r} contains invalid UTF-8 content."
            ) from exc


def _section_content(markdown: str, heading: str) -> str | None:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    if match is None:
        return None

    remainder = markdown[match.end():]
    next_heading = re.search(r"^##\s+", remainder, re.MULTILINE)
    end = next_heading.start() if next_heading else len(remainder)
    return remainder[:end].strip()


def _has_content(section: str | None) -> bool:
    if not section:
        return False
    return any(
        line.strip() and not line.lstrip().startswith("<!--")
        for line in section.splitlines()
    )


def assess_release_readiness(
    provider: ReleaseReadinessProvider,
    *,
    target_branch: str = DEFAULT_TARGET_BRANCH,
    workflow: str = DEFAULT_WORKFLOW,
) -> ReleaseReadiness:
    if target_branch != DEFAULT_TARGET_BRANCH:
        raise ReleaseReadinessError("Release target must be main.")
    if not workflow.strip():
        raise ReleaseReadinessError("Validation workflow must not be empty.")

    target = provider.get_branch(target_branch)
    blockers: list[str] = []

    if not target.protected:
        blockers.append("main must remain protected.")

    validation = provider.latest_successful_validation(workflow, target.sha)
    if validation is None:
        blockers.append(
            "No successful Aegis Validation run exists for the exact main SHA."
        )

    version_text = provider.get_file(VERSION_PATH, target_branch).strip()
    manifest_text = provider.get_file(MANIFEST_PATH, target_branch)
    registry_text = provider.get_file(REGISTRY_PATH, target_branch)
    changelog_text = provider.get_file(CHANGELOG_PATH, target_branch)

    try:
        manifest = parse_json_object(
            manifest_text,
            label="Release manifest JSON",
        )
        registry = parse_json_object(
            registry_text,
            label="Release skill registry JSON",
        )
    except EvidenceContractError as exc:
        raise ReleaseReadinessError(
            f"Release metadata contains invalid or ambiguous JSON: {exc}"
        ) from exc

    if not isinstance(manifest, Mapping) or not isinstance(registry, Mapping):
        raise ReleaseReadinessError(
            "Release metadata JSON must contain top-level objects."
        )

    manifest_version = manifest.get("version")
    registry_version = registry.get("version")
    version_valid = bool(RELEASE_VERSION_RE.fullmatch(version_text))

    if not version_valid:
        blockers.append(f"VERSION contains an invalid release version: {version_text!r}.")
    if manifest_version != version_text:
        blockers.append("VERSION and aegis-manifest.json disagree.")
    if registry_version != version_text:
        blockers.append("VERSION and skills/registry.json disagree.")

    version_section = _section_content(changelog_text, version_text)
    unreleased_section = _section_content(changelog_text, "Unreleased")

    changelog = ChangelogSnapshot(
        version_heading_present=version_section is not None,
        version_section_has_content=_has_content(version_section),
        unreleased_section_present=unreleased_section is not None,
        unreleased_content_present=_has_content(unreleased_section),
    )

    if not changelog.version_heading_present:
        blockers.append(
            f"CHANGELOG.md does not contain a version heading for {version_text}."
        )
    if not changelog.version_section_has_content:
        blockers.append(
            f"CHANGELOG.md version section for {version_text} is empty."
        )
    if changelog.unreleased_content_present:
        blockers.append(
            "CHANGELOG.md still contains unreleased notes that require release handling."
        )

    return ReleaseReadiness(
        repository=provider.repository,
        target=target,
        validation=validation,
        version=version_text,
        manifest_version=(
            manifest_version if isinstance(manifest_version, str) else None
        ),
        registry_version=(
            registry_version if isinstance(registry_version, str) else None
        ),
        version_valid=version_valid,
        changelog=changelog,
        blockers=tuple(blockers),
    )


def _to_dict(result: ReleaseReadiness) -> dict[str, Any]:
    return {
        "status": "ready" if result.ready else "blocked",
        "repository": result.repository,
        "target": {
            "branch": result.target.branch,
            "sha": result.target.sha,
            "protected": result.target.protected,
        },
        "validation": (
            {
                "id": result.validation.id,
                "workflow": result.validation.workflow,
                "status": result.validation.status,
                "conclusion": result.validation.conclusion,
                "head_sha": result.validation.head_sha,
                "url": result.validation.url,
            }
            if result.validation
            else None
        ),
        "versions": {
            "version": result.version,
            "manifest_version": result.manifest_version,
            "registry_version": result.registry_version,
            "version_valid": result.version_valid,
        },
        "changelog": {
            "version_heading_present": result.changelog.version_heading_present,
            "version_section_has_content": result.changelog.version_section_has_content,
            "unreleased_section_present": result.changelog.unreleased_section_present,
            "unreleased_content_present": result.changelog.unreleased_content_present,
        },
        "blockers": list(result.blockers),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify whether main is ready for a release."
    )
    parser.add_argument("repository")
    parser.add_argument("--target", default=DEFAULT_TARGET_BRANCH)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--evidence-output", type=os.path.abspath)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args()

    try:
        observed_at = datetime.now(timezone.utc)
        token = os.environ.get(args.token_env, "")
        provider = GitHubReleaseReadinessProvider(args.repository, token)
        result = assess_release_readiness(
            provider,
            target_branch=args.target,
            workflow=args.workflow,
        )
    except (ReleaseReadinessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    if args.evidence_output:
        from evidence_adapters import release_readiness_evidence
        from evidence_contract import write_evidence

        write_evidence(
            release_readiness_evidence(result, observed_at=observed_at),
            args.evidence_output,
        )

    print(json.dumps(_to_dict(result), indent=2, sort_keys=True))
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
