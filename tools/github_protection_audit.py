#!/usr/bin/env python3
"""Audit live GitHub repository rulesets used by Aegis protected branches."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from evidence_contract import EvidenceContractError, build_evidence, write_evidence
from github_http_security import (
    github_api_headers,
    parse_github_json,
    read_bounded_response,
    validate_github_api_base_url,
)

DEFAULT_API_BASE_URL = "https://api.github.com"
DEFAULT_BRANCHES = ("main", "develop", "ai/integration")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HTTPS_URL_RE = re.compile(r"^https://[^\\s]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class RulesetAuditError(RuntimeError):
    """Raised when live GitHub ruleset state cannot be audited safely."""


@dataclass(frozen=True, slots=True)
class RulesetSummary:
    """Relevant live controls for one active branch ruleset."""

    id: int
    name: str
    enforcement: str
    target: str
    include_refs: tuple[str, ...]
    exclude_refs: tuple[str, ...]
    requires_pull_request: bool
    required_approving_reviews: int | None
    required_status_checks: tuple[str, ...]
    strict_required_status_checks: bool | None
    requires_conversation_resolution: bool | None
    blocks_force_push: bool
    blocks_deletion: bool
    requires_linear_history: bool
    allowed_merge_methods: tuple[str, ...]
    bypass_actors: tuple[Mapping[str, Any], ...]
    html_url: str | None


class RulesetProvider(Protocol):
    repository: str

    def list_active_rulesets(self) -> list[Mapping[str, Any]]:
        ...


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent GitHub API requests from silently following redirects."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise RulesetAuditError("GitHub API returned an unexpected redirect.")


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
        raise RulesetAuditError("Unable to communicate with GitHub API.") from exc


class GitHubRulesetProvider:
    """Read-only GitHub repository ruleset provider."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        if not REPOSITORY_RE.fullmatch(repository):
            raise RulesetAuditError("Repository must use owner/name format.")
        if not token.strip():
            raise RulesetAuditError("GitHub API token must not be empty.")
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise RulesetAuditError(str(exc)) from exc
        self.repository = repository
        self._token = token
        self._transport = transport or _default_transport
        self._api_base_url = normalized_api_base_url

    def _request(self, method: str, path: str) -> tuple[int, Any]:
        if not path.startswith("/"):
            raise RulesetAuditError("GitHub API path must start with '/'.")
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            {"Authorization": f"Bearer {self._token}"},
            None,
        )

    def list_active_rulesets(self) -> list[Mapping[str, Any]]:
        rulesets: list[Mapping[str, Any]] = []
        for page in range(1, 101):
            query = urlencode({"per_page": 100, "page": page})
            status, data = self._request(
                "GET",
                f"/repos/{self.repository}/rulesets?{query}",
            )
            if status != 200 or not isinstance(data, list):
                raise RulesetAuditError(
                    f"Unable to read repository rulesets; HTTP {status}."
                )
            page_items = [item for item in data if isinstance(item, Mapping)]
            if len(page_items) != len(data):
                raise RulesetAuditError("GitHub rulesets response contains malformed entries.")
            rulesets.extend(page_items)
            if len(page_items) < 100:
                break
        else:
            raise RulesetAuditError("GitHub ruleset pagination exceeded the 100-page safety limit.")
        return rulesets


def _ref_conditions(ruleset: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    conditions = ruleset.get("conditions")
    if not isinstance(conditions, Mapping):
        raise RulesetAuditError("Ruleset conditions are malformed.")
    refs = conditions.get("ref_name")
    if not isinstance(refs, Mapping):
        raise RulesetAuditError("Ruleset ref_name conditions are missing.")
    include = refs.get("include")
    exclude = refs.get("exclude")
    if not isinstance(include, list) or not isinstance(exclude, list):
        raise RulesetAuditError("Ruleset ref_name include/exclude conditions are malformed.")
    if not all(isinstance(value, str) and value for value in include + exclude):
        raise RulesetAuditError("Ruleset ref_name conditions contain invalid values.")
    return tuple(include), tuple(exclude)


def _rule_map(ruleset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw_rules = ruleset.get("rules")
    if not isinstance(raw_rules, list):
        raise RulesetAuditError("Ruleset rules are malformed.")
    result: dict[str, Mapping[str, Any]] = {}
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, Mapping):
            raise RulesetAuditError("Ruleset contains a malformed rule.")
        rule_type = raw_rule.get("type")
        if not isinstance(rule_type, str) or not rule_type:
            raise RulesetAuditError("Ruleset rule type is malformed.")
        if rule_type in result:
            raise RulesetAuditError(f"Ruleset contains duplicate rule type {rule_type!r}.")
        result[rule_type] = raw_rule
    return result


def _rule_parameters(
    rules: Mapping[str, Mapping[str, Any]],
    rule_type: str,
) -> Mapping[str, Any]:
    rule = rules.get(rule_type)
    if rule is None:
        return {}
    parameters = rule.get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise RulesetAuditError(f"Ruleset rule {rule_type!r} parameters are malformed.")
    return parameters


def _parse_bypass_actors(
    ruleset: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    raw = ruleset.get("bypass_actors", [])
    if not isinstance(raw, list):
        raise RulesetAuditError("Ruleset bypass_actors are malformed.")
    actors: list[Mapping[str, Any]] = []
    for actor in raw:
        if not isinstance(actor, Mapping):
            raise RulesetAuditError("Ruleset bypass actor is malformed.")
        actor_type = actor.get("actor_type")
        bypass_mode = actor.get("bypass_mode")
        if not isinstance(actor_type, str) or not actor_type:
            raise RulesetAuditError("Ruleset bypass actor type is malformed.")
        if not isinstance(bypass_mode, str) or not bypass_mode:
            raise RulesetAuditError("Ruleset bypass mode is malformed.")
        actors.append({"actor_type": actor_type, "bypass_mode": bypass_mode})
    return tuple(sorted(actors, key=lambda value: (value["actor_type"], value["bypass_mode"])))


def summarize_ruleset(ruleset: Mapping[str, Any]) -> RulesetSummary:
    ruleset_id = ruleset.get("id")
    name = ruleset.get("name")
    enforcement = ruleset.get("enforcement")
    target = ruleset.get("target")
    if (
        not isinstance(ruleset_id, int)
        or ruleset_id <= 0
        or not isinstance(name, str)
        or not name.strip()
        or not isinstance(enforcement, str)
        or not isinstance(target, str)
    ):
        raise RulesetAuditError("GitHub ruleset identity is malformed.")

    include_refs, exclude_refs = _ref_conditions(ruleset)
    rules = _rule_map(ruleset)
    pull_params = _rule_parameters(rules, "pull_request")

    required_reviews = pull_params.get("required_approving_review_count")
    if required_reviews is not None and (
        not isinstance(required_reviews, int) or required_reviews < 0
    ):
        raise RulesetAuditError("Ruleset approving-review count is malformed.")

    conversation = pull_params.get("required_review_thread_resolution")
    if conversation is not None and not isinstance(conversation, bool):
        raise RulesetAuditError("Ruleset conversation-resolution value is malformed.")

    merge_methods = pull_params.get("allowed_merge_methods", [])
    if not isinstance(merge_methods, list) or not all(
        isinstance(value, str) and value for value in merge_methods
    ):
        raise RulesetAuditError("Ruleset merge-method configuration is malformed.")

    status_parameters = _rule_parameters(rules, "required_status_checks")
    raw_checks = status_parameters.get("required_status_checks", [])
    if not isinstance(raw_checks, list):
        raise RulesetAuditError("Ruleset required-status-checks list is malformed.")

    checks: list[str] = []
    for check in raw_checks:
        if not isinstance(check, Mapping) or not isinstance(check.get("context"), str):
            raise RulesetAuditError("Ruleset required status check is malformed.")
        checks.append(check["context"])

    html_url = None
    links = ruleset.get("_links")
    if isinstance(links, Mapping):
        html = links.get("html")
        if isinstance(html, Mapping):
            href = html.get("href")
            if isinstance(href, str) and HTTPS_URL_RE.fullmatch(href):
                html_url = href

    return RulesetSummary(
        id=ruleset_id,
        name=name,
        enforcement=enforcement,
        target=target,
        include_refs=tuple(sorted(include_refs)),
        exclude_refs=tuple(sorted(exclude_refs)),
        requires_pull_request="pull_request" in rules,
        required_approving_reviews=required_reviews,
        required_status_checks=tuple(sorted(checks)),
        strict_required_status_checks=(
            status_parameters.get("strict_required_status_checks_policy")
            if isinstance(status_parameters.get("strict_required_status_checks_policy"), bool)
            else None
        ),
        requires_conversation_resolution=conversation,
        blocks_force_push="non_fast_forward" in rules,
        blocks_deletion="deletion" in rules,
        requires_linear_history="required_linear_history" in rules,
        allowed_merge_methods=tuple(sorted(merge_methods)),
        bypass_actors=_parse_bypass_actors(ruleset),
        html_url=html_url,
    )


def _covers_branch(summary: RulesetSummary, branch: str) -> bool:
    target = f"refs/heads/{branch}"
    return (
        summary.target == "branch"
        and summary.enforcement == "active"
        and target in summary.include_refs
        and target not in summary.exclude_refs
    )


def _validate_branches(branches: tuple[str, ...]) -> None:
    if not branches:
        raise RulesetAuditError("At least one branch must be requested.")
    if len(set(branches)) != len(branches):
        raise RulesetAuditError("Duplicate branch names are not allowed.")
    for branch in branches:
        if not isinstance(branch, str) or not BRANCH_RE.fullmatch(branch):
            raise RulesetAuditError("Requested branch names contain unsupported characters.")


def audit_branches(
    provider: RulesetProvider,
    branches: tuple[str, ...] = DEFAULT_BRANCHES,
) -> dict[str, Any]:
    _validate_branches(branches)
    summaries = [summarize_ruleset(item) for item in provider.list_active_rulesets()]

    result: dict[str, Any] = {}
    for branch in branches:
        matches = sorted(
            (summary for summary in summaries if _covers_branch(summary, branch)),
            key=lambda summary: summary.id,
        )
        if len(matches) != 1:
            raise RulesetAuditError(
                f"Expected exactly one active branch ruleset for {branch!r}; found {len(matches)}."
            )

        summary = matches[0]
        result[branch] = {
            "ruleset": {
                "id": summary.id,
                "name": summary.name,
                "enforcement": summary.enforcement,
                "target": summary.target,
                "html_url": summary.html_url,
            },
            "ref_name": {
                "include": list(summary.include_refs),
                "exclude": list(summary.exclude_refs),
            },
            "pull_request": {
                "required": summary.requires_pull_request,
                "required_approving_reviews": summary.required_approving_reviews,
                "required_review_thread_resolution": summary.requires_conversation_resolution,
                "allowed_merge_methods": list(summary.allowed_merge_methods),
            },
            "required_status_checks": {
                "contexts": list(summary.required_status_checks),
                "strict": summary.strict_required_status_checks,
            },
            "branch_controls": {
                "blocks_force_push": summary.blocks_force_push,
                "blocks_deletion": summary.blocks_deletion,
                "requires_linear_history": summary.requires_linear_history,
            },
            "bypass_actors": [dict(actor) for actor in summary.bypass_actors],
        }

    return {"repository": provider.repository, "branches": result}


def build_audit_evidence(
    result: Mapping[str, Any],
    *,
    observed_at: datetime | str,
) -> Any:
    timestamp = (
        observed_at.isoformat(timespec="seconds")
        if isinstance(observed_at, datetime)
        else observed_at
    )
    repository = result.get("repository")
    branches = result.get("branches")
    if not isinstance(repository, str) or not repository:
        raise EvidenceContractError("Ruleset audit repository is required.")
    if not isinstance(branches, Mapping) or not branches:
        raise EvidenceContractError("Ruleset audit branches are required.")

    references: list[str] = []
    for value in branches.values():
        ruleset = value.get("ruleset") if isinstance(value, Mapping) else None
        url = ruleset.get("html_url") if isinstance(ruleset, Mapping) else None
        if isinstance(url, str) and HTTPS_URL_RE.fullmatch(url):
            references.append(url)

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "github-ruleset-audit",
            "source": f"github:{repository}",
            "subject": f"rulesets:{repository}",
            "revision": None,
            "observed_at": timestamp,
            "status": "verified",
            "result": dict(result),
            "uncertainty": [],
            "references": sorted(set(references)),
            "artifact_sha256": None,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read and audit live GitHub repository rulesets for Aegis protected branches."
    )
    parser.add_argument("repository")
    parser.add_argument(
        "--branch",
        action="append",
        dest="branches",
        help="Protected branch to inspect. Repeat for multiple branches.",
    )
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument(
        "--canonical-evidence-output",
        type=str,
        help="Optional canonical evidence-provenance output path.",
    )
    args = parser.parse_args()

    try:
        token = os.environ.get(args.token_env, "")
        provider = GitHubRulesetProvider(
            args.repository,
            token,
            api_base_url=args.api_base_url,
        )
        result = audit_branches(
            provider,
            tuple(args.branches) if args.branches else DEFAULT_BRANCHES,
        )
        if args.canonical_evidence_output:
            evidence = build_audit_evidence(
                result,
                observed_at=datetime.now(timezone.utc),
            )
            write_evidence(evidence, args.canonical_evidence_output)
    except (RulesetAuditError, EvidenceContractError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
