#!/usr/bin/env python3
"""Execute provider-neutral work-item lifecycle operations.

The core lifecycle model is provider-independent. GitHub Issues is one adapter
that persists the lifecycle state through controlled labels, issue state, and
traceability comments.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


GITHUB_API_VERSION = "2026-03-10"
DEFAULT_TIMEOUT_SECONDS = 30.0
STATUS_LABEL_PREFIX = "aegis:status:"
RESUME_LABEL_PREFIX = "aegis:resume:"
STATUS_LABEL_RE = re.compile(r"^aegis:status:[a-z_]+$")
RESUME_LABEL_RE = re.compile(r"^aegis:resume:[a-z_]+$")
BRANCH_RE = re.compile(r"^ai/(feature|fix|refactor|chore)/[A-Za-z0-9._/-]+$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)
HTTPS_URL_RE = re.compile(r"^https://[^\s]+$")


class LifecycleState(StrEnum):
    INTAKE = "intake"
    PLANNED = "planned"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    VERIFICATION = "verification"
    REVIEW = "review"
    INTEGRATION = "integration"
    BLOCKED = "blocked"
    DONE = "done"


ACTIVE_STATES = frozenset(
    {
        LifecycleState.INTAKE,
        LifecycleState.PLANNED,
        LifecycleState.READY,
        LifecycleState.IN_PROGRESS,
        LifecycleState.VERIFICATION,
        LifecycleState.REVIEW,
        LifecycleState.INTEGRATION,
    }
)

TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.INTAKE: frozenset({LifecycleState.PLANNED, LifecycleState.BLOCKED}),
    LifecycleState.PLANNED: frozenset({LifecycleState.READY, LifecycleState.BLOCKED}),
    LifecycleState.READY: frozenset({LifecycleState.IN_PROGRESS, LifecycleState.BLOCKED}),
    LifecycleState.IN_PROGRESS: frozenset(
        {LifecycleState.VERIFICATION, LifecycleState.BLOCKED}
    ),
    LifecycleState.VERIFICATION: frozenset(
        {LifecycleState.REVIEW, LifecycleState.BLOCKED}
    ),
    LifecycleState.REVIEW: frozenset(
        {LifecycleState.INTEGRATION, LifecycleState.BLOCKED}
    ),
    LifecycleState.INTEGRATION: frozenset({LifecycleState.DONE, LifecycleState.BLOCKED}),
    LifecycleState.BLOCKED: frozenset(ACTIVE_STATES),
    LifecycleState.DONE: frozenset(),
}


class WorkItemLifecycleError(RuntimeError):
    """Raised when a lifecycle operation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class Traceability:
    """External references attached to one work item."""

    branch: str | None = None
    pull_request_url: str | None = None
    evidence_ref: str | None = None
    conversation_id: str | None = None

    def validate(self) -> None:
        if self.branch is not None and not BRANCH_RE.fullmatch(self.branch):
            raise WorkItemLifecycleError("Traceability branch must use the ai/* branch policy.")
        if self.pull_request_url is not None and not HTTPS_URL_RE.fullmatch(
            self.pull_request_url
        ):
            raise WorkItemLifecycleError("Traceability pull request URL must be HTTPS.")
        if self.evidence_ref is not None:
            if "\n" in self.evidence_ref or "\r" in self.evidence_ref:
                raise WorkItemLifecycleError("Evidence reference must not contain newlines.")
            if len(self.evidence_ref) > 500:
                raise WorkItemLifecycleError("Evidence reference is too long.")
        if self.conversation_id is not None and not UUID_RE.fullmatch(
            self.conversation_id
        ):
            raise WorkItemLifecycleError("Conversation ID must be a UUID.")


@dataclass(frozen=True, slots=True)
class WorkItem:
    """Provider-neutral work item representation."""

    id: str
    title: str
    state: LifecycleState
    provider: str
    provider_url: str | None = None
    labels: tuple[str, ...] = ()
    resume_state: LifecycleState | None = None


@dataclass(frozen=True, slots=True)
class MutationEvidence:
    """Safe evidence for one provider mutation."""

    provider: str
    operation: str
    work_item_id: str
    state_before: str | None = None
    state_after: str | None = None
    verified: bool = False
    reference: str | None = None


class WorkItemProvider(Protocol):
    """Minimal provider-neutral work-item contract."""

    def get(self, work_item_id: str) -> WorkItem:
        ...

    def transition(
        self,
        work_item_id: str,
        target: LifecycleState,
        *,
        expected_state: LifecycleState | None = None,
    ) -> MutationEvidence:
        ...

    def comment(
        self,
        work_item_id: str,
        body: str,
    ) -> MutationEvidence:
        ...

    def attach_traceability(
        self,
        work_item_id: str,
        traceability: Traceability,
    ) -> MutationEvidence:
        ...


def validate_transition(
    current: LifecycleState,
    target: LifecycleState,
    *,
    resume_state: LifecycleState | None = None,
) -> None:
    """Fail closed when a requested lifecycle transition is invalid."""
    if current == LifecycleState.BLOCKED:
        if resume_state is None:
            raise WorkItemLifecycleError("Blocked work item has no recorded resume state.")
        if target != resume_state:
            raise WorkItemLifecycleError(
                f"Blocked work item must resume at {resume_state.value}; "
                f"requested {target.value}."
            )
        return
    if target not in TRANSITIONS[current]:
        raise WorkItemLifecycleError(
            f"Invalid lifecycle transition: {current.value} -> {target.value}."
        )


def render_traceability_comment(traceability: Traceability) -> str:
    """Render a deterministic machine-readable traceability comment."""
    traceability.validate()
    fields = (
        ("Branch", traceability.branch),
        ("Pull request", traceability.pull_request_url),
        ("Evidence", traceability.evidence_ref),
        ("OpenHands conversation", traceability.conversation_id),
    )
    lines = ["<!-- aegis:traceability:v1 -->", "## Aegis traceability"]
    for label, value in fields:
        if value is not None:
            lines.append(f"- **{label}:** {value}")
    if len(lines) == 2:
        raise WorkItemLifecycleError("Traceability must contain at least one reference.")
    return "\n".join(lines)


def _redact(value: Any) -> Any:
    """Redact common credentials from provider responses before evidence use."""
    sensitive = {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "api_key",
    }
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if key.lower() in sensitive else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent an API endpoint from silently redirecting to another host."""

    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> Request:
        raise WorkItemLifecycleError("GitHub API returned an unexpected redirect.")


_HTTP_OPENER = build_opener(_NoRedirectHandler)


JsonTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None],
    tuple[int, Any],
]


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
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
        with _HTTP_OPENER.open(request, timeout=timeout) as response:
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
        raise WorkItemLifecycleError(
            f"Unable to communicate with GitHub API endpoint {url}: {exc}"
        ) from exc


class GitHubIssuesProvider:
    """Persist Aegis lifecycle state through GitHub Issues."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = "https://api.github.com",
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise WorkItemLifecycleError("GitHub repository must be owner/name.")
        if not token.strip():
            raise WorkItemLifecycleError("GitHub API token must not be empty.")
        parsed = urlparse(api_base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise WorkItemLifecycleError("GitHub API base URL must be an HTTPS service root.")
        self.repository = repository
        self._token = token
        self._transport = transport or _default_transport
        self._api_base_url = api_base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not path.startswith("/"):
            raise WorkItemLifecycleError("GitHub API path must start with '/'.")
        headers = {"Authorization": f"Bearer {self._token}"}
        return self._transport(
            method,
            f"{self._api_base_url}{path}",
            headers,
            payload,
        )

    def _issue_path(self, work_item_id: str) -> str:
        if not work_item_id.isdigit():
            raise WorkItemLifecycleError("GitHub work-item ID must be a numeric issue number.")
        return f"/repos/{self.repository}/issues/{int(work_item_id)}"

    @staticmethod
    def _extract_state(labels: list[str]) -> LifecycleState:
        state_values = [
            label.removeprefix(STATUS_LABEL_PREFIX)
            for label in labels
            if STATUS_LABEL_RE.fullmatch(label)
        ]
        invalid = [
            value
            for value in state_values
            if value not in LifecycleState._value2member_map_
        ]
        if invalid:
            raise WorkItemLifecycleError(
                f"GitHub issue contains invalid Aegis status labels: {invalid!r}."
            )
        states = [LifecycleState(value) for value in state_values]
        if len(states) > 1:
            raise WorkItemLifecycleError("GitHub issue contains multiple Aegis status labels.")
        if states:
            return states[0]
        return LifecycleState.INTAKE

    @staticmethod
    def _extract_resume_state(
        labels: list[str],
        state: LifecycleState,
    ) -> LifecycleState | None:
        resume_values = [
            label.removeprefix(RESUME_LABEL_PREFIX)
            for label in labels
            if RESUME_LABEL_RE.fullmatch(label)
        ]
        if state != LifecycleState.BLOCKED:
            if resume_values:
                raise WorkItemLifecycleError(
                    "Non-blocked GitHub issue contains a stale Aegis resume label."
                )
            return None
        if len(resume_values) != 1:
            raise WorkItemLifecycleError(
                "Blocked GitHub issue must contain exactly one Aegis resume label."
            )
        value = resume_values[0]
        if value not in {item.value for item in ACTIVE_STATES}:
            raise WorkItemLifecycleError("Aegis resume label contains an invalid lifecycle state.")
        return LifecycleState(value)

    def get(self, work_item_id: str) -> WorkItem:
        status, data = self._request("GET", self._issue_path(work_item_id))
        if status != 200 or not isinstance(data, Mapping):
            raise WorkItemLifecycleError(
                f"Unable to read GitHub issue #{work_item_id}; HTTP {status}."
            )
        raw_labels = data.get("labels", [])
        if not isinstance(raw_labels, list):
            raise WorkItemLifecycleError("GitHub issue labels response is malformed.")
        labels = tuple(
            sorted(
                label.get("name")
                for label in raw_labels
                if isinstance(label, Mapping) and isinstance(label.get("name"), str)
            )
        )
        state = self._extract_state(list(labels))
        resume_state = self._extract_resume_state(list(labels), state)
        if state == LifecycleState.DONE and data.get("state") != "closed":
            raise WorkItemLifecycleError("Aegis done state requires a closed GitHub issue.")
        if state != LifecycleState.DONE and data.get("state") != "open":
            raise WorkItemLifecycleError(
                "Aegis non-terminal state requires an open GitHub issue."
            )
        html_url = data.get("html_url")
        return WorkItem(
            id=str(work_item_id),
            title=str(data.get("title", "")),
            state=state,
            provider="github-issues",
            provider_url=html_url if isinstance(html_url, str) else None,
            labels=labels,
            resume_state=resume_state,
        )

    def _ensure_status_label(self, state: LifecycleState) -> None:
        label_name = f"{STATUS_LABEL_PREFIX}{state.value}"
        path = f"/repos/{self.repository}/labels/{quote(label_name, safe='')}"
        status, data = self._request("GET", path)
        if status == 200:
            return
        if status != 404:
            raise WorkItemLifecycleError(
                f"Unable to inspect Aegis status label {label_name!r}; HTTP {status}."
            )
        create_path = f"/repos/{self.repository}/labels"
        status, data = self._request(
            "POST",
            create_path,
            {
                "name": label_name,
                "description": f"Aegis lifecycle state: {state.value}.",
                "color": "6f42c1",
            },
        )
        if status not in {200, 201}:
            raise WorkItemLifecycleError(
                f"Unable to create Aegis status label {label_name!r}; HTTP {status}."
            )
        self._verify_label_exists(label_name)

    def _ensure_resume_label(self, state: LifecycleState) -> None:
        label_name = f"{RESUME_LABEL_PREFIX}{state.value}"
        path = f"/repos/{self.repository}/labels/{quote(label_name, safe='')}"
        status, _ = self._request("GET", path)
        if status == 200:
            return
        if status != 404:
            raise WorkItemLifecycleError(
                f"Unable to inspect Aegis resume label {label_name!r}; HTTP {status}."
            )
        status, _ = self._request(
            "POST",
            f"/repos/{self.repository}/labels",
            {
                "name": label_name,
                "description": f"Aegis blocked-work resume target: {state.value}.",
                "color": "8250df",
            },
        )
        if status not in {200, 201}:
            raise WorkItemLifecycleError(
                f"Unable to create Aegis resume label {label_name!r}; HTTP {status}."
            )
        self._verify_label_exists(label_name)

    def _verify_label_exists(self, label_name: str) -> None:
        path = f"/repos/{self.repository}/labels/{quote(label_name, safe='')}"
        status, _ = self._request("GET", path)
        if status != 200:
            raise WorkItemLifecycleError(
                f"GitHub status label {label_name!r} was not readable after mutation."
            )

    def transition(
        self,
        work_item_id: str,
        target: LifecycleState,
        *,
        expected_state: LifecycleState | None = None,
    ) -> MutationEvidence:
        current = self.get(work_item_id)
        if expected_state is not None and current.state != expected_state:
            raise WorkItemLifecycleError(
                f"Work item #{work_item_id} state changed concurrently: "
                f"expected {expected_state.value}, got {current.state.value}."
            )
        validate_transition(
            current.state,
            target,
            resume_state=current.resume_state,
        )
        self._ensure_status_label(target)
        if target == LifecycleState.BLOCKED:
            if current.state not in ACTIVE_STATES:
                raise WorkItemLifecycleError(
                    "Only active work items can enter blocked state."
                )
            self._ensure_resume_label(current.state)

        labels = [
            label
            for label in current.labels
            if not STATUS_LABEL_RE.fullmatch(label)
            and not RESUME_LABEL_RE.fullmatch(label)
        ]
        labels.append(f"{STATUS_LABEL_PREFIX}{target.value}")
        if target == LifecycleState.BLOCKED:
            labels.append(f"{RESUME_LABEL_PREFIX}{current.state.value}")
        payload: dict[str, Any] = {
            "labels": sorted(labels),
            "state": "closed" if target == LifecycleState.DONE else "open",
        }
        if target == LifecycleState.DONE:
            payload["state_reason"] = "completed"
        elif current.state == LifecycleState.DONE:
            payload["state_reason"] = "reopened"

        status, _ = self._request("PATCH", self._issue_path(work_item_id), payload)
        if status != 200:
            raise WorkItemLifecycleError(
                f"Unable to transition GitHub issue #{work_item_id}; HTTP {status}."
            )

        verified = self.get(work_item_id)
        if verified.state != target:
            raise WorkItemLifecycleError(
                f"GitHub issue #{work_item_id} did not verify as {target.value} after mutation."
            )
        return MutationEvidence(
            provider="github-issues",
            operation="transition",
            work_item_id=work_item_id,
            state_before=current.state.value,
            state_after=verified.state.value,
            verified=True,
            reference=verified.provider_url,
        )

    def comment(self, work_item_id: str, body: str) -> MutationEvidence:
        if not body.strip():
            raise WorkItemLifecycleError("Work-item comment must not be empty.")
        if len(body) > 65000:
            raise WorkItemLifecycleError("Work-item comment is too large.")
        status, data = self._request(
            "POST",
            f"{self._issue_path(work_item_id)}/comments",
            {"body": body},
        )
        if status not in {200, 201} or not isinstance(data, Mapping):
            raise WorkItemLifecycleError(
                f"Unable to add GitHub issue comment to #{work_item_id}; HTTP {status}."
            )
        comment_id = data.get("id")
        if not isinstance(comment_id, int):
            raise WorkItemLifecycleError("GitHub issue comment did not return an ID.")

        verify_status, verify_data = self._request(
            "GET",
            f"/repos/{self.repository}/issues/comments/{comment_id}",
        )
        if (
            verify_status != 200
            or not isinstance(verify_data, Mapping)
            or verify_data.get("body") != body
        ):
            raise WorkItemLifecycleError(
                f"GitHub issue comment #{comment_id} failed read-after-write verification."
            )

        return MutationEvidence(
            provider="github-issues",
            operation="comment",
            work_item_id=work_item_id,
            verified=True,
            reference=str(data.get("html_url")) if data.get("html_url") else None,
        )

    def attach_traceability(
        self,
        work_item_id: str,
        traceability: Traceability,
    ) -> MutationEvidence:
        body = render_traceability_comment(traceability)
        return self.comment(work_item_id, body)


class InMemoryWorkItemProvider:
    """Small deterministic provider used for policy and lifecycle tests."""

    def __init__(self, items: Mapping[str, WorkItem]) -> None:
        self.items = dict(items)
        self.comments: dict[str, list[str]] = {}

    def get(self, work_item_id: str) -> WorkItem:
        try:
            return self.items[work_item_id]
        except KeyError as exc:
            raise WorkItemLifecycleError(f"Unknown work item: {work_item_id}.") from exc

    def transition(
        self,
        work_item_id: str,
        target: LifecycleState,
        *,
        expected_state: LifecycleState | None = None,
    ) -> MutationEvidence:
        current = self.get(work_item_id)
        if expected_state is not None and current.state != expected_state:
            raise WorkItemLifecycleError("Concurrent lifecycle change detected.")
        validate_transition(current.state, target, resume_state=current.resume_state)
        updated = WorkItem(
            id=current.id,
            title=current.title,
            state=target,
            provider=current.provider,
            provider_url=current.provider_url,
            labels=current.labels,
            resume_state=None if target != LifecycleState.BLOCKED else current.state,
        )
        self.items[work_item_id] = updated
        return MutationEvidence(
            provider=current.provider,
            operation="transition",
            work_item_id=work_item_id,
            state_before=current.state.value,
            state_after=target.value,
            verified=True,
            reference=current.provider_url,
        )

    def comment(self, work_item_id: str, body: str) -> MutationEvidence:
        self.get(work_item_id)
        self.comments.setdefault(work_item_id, []).append(body)
        return MutationEvidence(
            provider="memory",
            operation="comment",
            work_item_id=work_item_id,
            verified=True,
        )

    def attach_traceability(
        self,
        work_item_id: str,
        traceability: Traceability,
    ) -> MutationEvidence:
        return self.comment(work_item_id, render_traceability_comment(traceability))


def _build_provider(args: argparse.Namespace) -> GitHubIssuesProvider:
    token = os.environ.get(args.token_env, "")
    return GitHubIssuesProvider(args.repository, token)


def _print_evidence(evidence: MutationEvidence) -> None:
    print(
        json.dumps(
            {
                "status": "verified",
                "provider": evidence.provider,
                "operation": evidence.operation,
                "work_item_id": evidence.work_item_id,
                "state_before": evidence.state_before,
                "state_after": evidence.state_after,
                "verified": evidence.verified,
                "reference": evidence.reference,
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage an Aegis work-item lifecycle.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    transition = subparsers.add_parser("transition")
    transition.add_argument("repository")
    transition.add_argument("issue_number")
    transition.add_argument("target_state", choices=[state.value for state in LifecycleState])
    transition.add_argument("--expected-state", choices=[state.value for state in LifecycleState])
    transition.add_argument("--dry-run", action="store_true")
    transition.add_argument("--token-env", default="GITHUB_TOKEN")

    comment = subparsers.add_parser("comment")
    comment.add_argument("repository")
    comment.add_argument("issue_number")
    comment.add_argument("body")
    comment.add_argument("--token-env", default="GITHUB_TOKEN")

    trace = subparsers.add_parser("trace")
    trace.add_argument("repository")
    trace.add_argument("issue_number")
    trace.add_argument("--branch")
    trace.add_argument("--pull-request-url")
    trace.add_argument("--evidence-ref")
    trace.add_argument("--conversation-id")
    trace.add_argument("--token-env", default="GITHUB_TOKEN")

    args = parser.parse_args()

    try:
        if args.command == "transition":
            provider = _build_provider(args)
            current = provider.get(args.issue_number)
            target = LifecycleState(args.target_state)
            expected = LifecycleState(args.expected_state) if args.expected_state else None
            if expected is not None and current.state != expected:
                raise WorkItemLifecycleError(
                    f"Expected {expected.value}, but issue is {current.state.value}."
                )
            validate_transition(
                current.state,
                target,
                resume_state=current.resume_state,
            )
            if args.dry_run:
                print(
                    json.dumps(
                        {
                            "status": "dry-run",
                            "work_item_id": args.issue_number,
                            "state_before": current.state.value,
                            "state_after": target.value,
                            "provider": "github-issues",
                        },
                        indent=2,
                    )
                )
                return 0
            _print_evidence(
                provider.transition(
                    args.issue_number,
                    target,
                    expected_state=expected,
                )
            )
            return 0

        if args.command == "comment":
            provider = _build_provider(args)
            _print_evidence(provider.comment(args.issue_number, args.body))
            return 0

        traceability = Traceability(
            branch=args.branch,
            pull_request_url=args.pull_request_url,
            evidence_ref=args.evidence_ref,
            conversation_id=args.conversation_id,
        )
        provider = _build_provider(args)
        _print_evidence(
            provider.attach_traceability(args.issue_number, traceability)
        )
    except (WorkItemLifecycleError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
