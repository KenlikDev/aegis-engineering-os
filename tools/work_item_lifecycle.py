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
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from github_http_security import (
    github_api_headers,
    parse_github_json,
    read_bounded_response,
    validate_github_api_base_url,
)


DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_LOCK_LEASE_SECONDS = 300.0
MAX_LOCK_LEASE_SECONDS = 900.0
LIFECYCLE_LOCK_REF_PREFIX = "refs/aegis/locks/work-item/"
LIFECYCLE_LOCK_HEADER = "Aegis lifecycle lock v1"
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
    identifier: int | str | None = None


def require_verified_mutation(
    mutation: MutationEvidence,
    context: str,
) -> MutationEvidence:
    """Require explicit read-after-write verification for a material mutation."""
    if not isinstance(context, str) or not context.strip():
        raise WorkItemLifecycleError("Mutation verification context must not be empty.")
    if not mutation.verified:
        raise WorkItemLifecycleError(
            f"{context} was not read-after-write verified."
        )
    return mutation


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
    request_headers = github_api_headers()
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
            raw = read_bounded_response(response)
            return response.status, parse_github_json(raw) if raw else {}
    except HTTPError as exc:
        raw = read_bounded_response(exc)
        try:
            data = parse_github_json(raw) if raw else {}
        except ValueError as parse_error:
            raise WorkItemLifecycleError(
                f"GitHub API returned invalid JSON error response: {parse_error}"
            ) from parse_error
        return exc.code, data
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise WorkItemLifecycleError(
            f"Unable to communicate with GitHub API endpoint {url}: {exc}"
        ) from exc


@dataclass(frozen=True, slots=True)
class _LifecycleLock:
    work_item_id: str
    owner: str
    ref_sha: str


class GitHubIssuesProvider:
    """Persist Aegis lifecycle state through GitHub Issues."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: JsonTransport | None = None,
        api_base_url: str = "https://api.github.com",
        lock_lease_seconds: float = DEFAULT_LOCK_LEASE_SECONDS,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise WorkItemLifecycleError("GitHub repository must be owner/name.")
        if not token.strip():
            raise WorkItemLifecycleError("GitHub API token must not be empty.")
        if not isinstance(lock_lease_seconds, (int, float)) or isinstance(
            lock_lease_seconds, bool
        ):
            raise WorkItemLifecycleError("Lifecycle lock lease must be numeric.")
        if not 0 < float(lock_lease_seconds) <= MAX_LOCK_LEASE_SECONDS:
            raise WorkItemLifecycleError(
                f"Lifecycle lock lease must be between 0 and {MAX_LOCK_LEASE_SECONDS} seconds."
            )
        try:
            normalized_api_base_url = validate_github_api_base_url(api_base_url)
        except ValueError as exc:
            raise WorkItemLifecycleError(str(exc)) from exc
        self.repository = repository
        self._token = token
        self._transport = transport or _default_transport
        self._api_base_url = normalized_api_base_url
        self._lock_lease_seconds = float(lock_lease_seconds)

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
        state_labels_present = any(
            STATUS_LABEL_RE.fullmatch(label) for label in labels
        )
        if not state_labels_present:
            if data.get("state") == "closed":
                raise WorkItemLifecycleError(
                    "GitHub issue is closed without an Aegis status label; "
                    "refusing to infer lifecycle completion."
                )
            state = LifecycleState.INTAKE
        else:
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

        lock = self._acquire_lifecycle_lock(work_item_id)
        try:
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
            evidence = MutationEvidence(
                provider="github-issues",
                operation="transition",
                work_item_id=work_item_id,
                state_before=current.state.value,
                state_after=verified.state.value,
                verified=True,
                reference=verified.provider_url,
            )
        except Exception:
            self._release_lifecycle_lock(lock)
            raise
        self._release_lifecycle_lock(lock)
        return evidence

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

    def _lifecycle_lock_ref_name(self, work_item_id: str) -> str:
        if not work_item_id.isdigit():
            raise WorkItemLifecycleError("GitHub work-item ID must be a numeric issue number.")
        return f"{LIFECYCLE_LOCK_REF_PREFIX}{int(work_item_id)}"

    def _lifecycle_lock_ref_path(self, work_item_id: str) -> str:
        ref_name = self._lifecycle_lock_ref_name(work_item_id)
        return f"/repos/{self.repository}/git/ref/{quote(ref_name.removeprefix('refs/'), safe='/')}"

    def _get_ref_sha(self, path: str) -> str:
        status, data = self._request("GET", path)
        if status != 200 or not isinstance(data, Mapping):
            raise WorkItemLifecycleError(f"Unable to read Git ref; HTTP {status}.")
        obj = data.get("object")
        if not isinstance(obj, Mapping) or not isinstance(obj.get("sha"), str):
            raise WorkItemLifecycleError("Git ref response did not contain a commit SHA.")
        return obj["sha"]

    def _get_commit_tree_sha(self, commit_sha: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
            raise WorkItemLifecycleError("Git commit SHA is malformed.")
        status, data = self._request(
            "GET",
            f"/repos/{self.repository}/git/commits/{commit_sha}",
        )
        if status != 200 or not isinstance(data, Mapping):
            raise WorkItemLifecycleError(
                f"Unable to read Git commit {commit_sha}; HTTP {status}."
            )
        tree = data.get("tree")
        if not isinstance(tree, Mapping) or not isinstance(tree.get("sha"), str):
            raise WorkItemLifecycleError("Git commit response did not contain a tree SHA.")
        return tree["sha"]

    @staticmethod
    def _render_lifecycle_lock_message(
        work_item_id: str,
        *,
        mode: str,
        owner: str,
        expires_at: datetime | None,
    ) -> str:
        if mode not in {"held", "free"}:
            raise WorkItemLifecycleError("Lifecycle lock mode is invalid.")
        if not UUID_RE.fullmatch(owner):
            raise WorkItemLifecycleError("Lifecycle lock owner must be a UUID.")
        expires_text = (
            expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if expires_at is not None
            else "-"
        )
        return "\n".join(
            (
                LIFECYCLE_LOCK_HEADER,
                f"work-item: {int(work_item_id)}",
                f"mode: {mode}",
                f"owner: {owner}",
                f"expires-at: {expires_text}",
            )
        )

    @staticmethod
    def _parse_lifecycle_lock_message(
        work_item_id: str,
        message: str,
    ) -> tuple[str, str, datetime | None]:
        fields: dict[str, str] = {}
        lines = message.splitlines()
        if not lines or lines[0] != LIFECYCLE_LOCK_HEADER:
            raise WorkItemLifecycleError("Lifecycle lock ref contains an unknown commit format.")
        for line in lines[1:]:
            key, separator, value = line.partition(": ")
            if separator:
                fields[key] = value
        if fields.get("work-item") != str(int(work_item_id)):
            raise WorkItemLifecycleError("Lifecycle lock ref belongs to another work item.")
        mode = fields.get("mode")
        owner = fields.get("owner")
        expires_text = fields.get("expires-at")
        if mode not in {"held", "free"} or not isinstance(owner, str):
            raise WorkItemLifecycleError("Lifecycle lock ref contains invalid lock metadata.")
        if not UUID_RE.fullmatch(owner):
            raise WorkItemLifecycleError("Lifecycle lock owner must be a UUID.")
        if mode == "free":
            if expires_text != "-":
                raise WorkItemLifecycleError("Free lifecycle lock must not contain an expiry.")
            return mode, owner, None
        if not expires_text or expires_text == "-":
            raise WorkItemLifecycleError("Held lifecycle lock must contain an expiry.")
        try:
            expires_at = datetime.fromisoformat(expires_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WorkItemLifecycleError("Lifecycle lock expiry is malformed.") from exc
        if expires_at.tzinfo is None:
            raise WorkItemLifecycleError("Lifecycle lock expiry must include a timezone.")
        return mode, owner, expires_at.astimezone(timezone.utc)

    def _create_lifecycle_lock_commit(
        self,
        parent_sha: str,
        *,
        work_item_id: str,
        mode: str,
        owner: str,
        expires_at: datetime | None,
    ) -> str:
        tree_sha = self._get_commit_tree_sha(parent_sha)
        status, data = self._request(
            "POST",
            f"/repos/{self.repository}/git/commits",
            {
                "message": self._render_lifecycle_lock_message(
                    work_item_id,
                    mode=mode,
                    owner=owner,
                    expires_at=expires_at,
                ),
                "tree": tree_sha,
                "parents": [parent_sha],
            },
        )
        if status != 201 or not isinstance(data, Mapping):
            raise WorkItemLifecycleError(
                f"Unable to create lifecycle lock commit; HTTP {status}."
            )
        sha = data.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise WorkItemLifecycleError("Lifecycle lock commit did not return a valid SHA.")
        return sha

    def _read_lifecycle_lock(
        self,
        work_item_id: str,
    ) -> tuple[str, str, str, datetime | None] | None:
        status, data = self._request("GET", self._lifecycle_lock_ref_path(work_item_id))
        if status == 404:
            return None
        if status != 200 or not isinstance(data, Mapping):
            raise WorkItemLifecycleError(
                f"Unable to inspect lifecycle lock for #{work_item_id}; HTTP {status}."
            )
        obj = data.get("object")
        if not isinstance(obj, Mapping) or not isinstance(obj.get("sha"), str):
            raise WorkItemLifecycleError("Lifecycle lock ref did not contain an object SHA.")
        ref_sha = obj["sha"]
        status, commit = self._request(
            "GET",
            f"/repos/{self.repository}/git/commits/{ref_sha}",
        )
        if status != 200 or not isinstance(commit, Mapping):
            raise WorkItemLifecycleError(
                f"Unable to read lifecycle lock commit {ref_sha}; HTTP {status}."
            )
        message = commit.get("message")
        if not isinstance(message, str):
            raise WorkItemLifecycleError("Lifecycle lock commit did not contain a message.")
        mode, owner, expires_at = self._parse_lifecycle_lock_message(work_item_id, message)
        return ref_sha, mode, owner, expires_at

    def _acquire_lifecycle_lock(self, work_item_id: str) -> _LifecycleLock:
        ref_name = self._lifecycle_lock_ref_name(work_item_id)
        ref_path = self._lifecycle_lock_ref_path(work_item_id)
        owner = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._lock_lease_seconds)

        for _ in range(4):
            current = self._read_lifecycle_lock(work_item_id)
            if current is None:
                integration_sha = self._get_ref_sha(
                    f"/repos/{self.repository}/git/ref/heads/ai/integration"
                )
                lock_sha = self._create_lifecycle_lock_commit(
                    integration_sha,
                    work_item_id=work_item_id,
                    mode="held",
                    owner=owner,
                    expires_at=expires_at,
                )
                status, _ = self._request(
                    "POST",
                    f"/repos/{self.repository}/git/refs",
                    {"ref": ref_name, "sha": lock_sha},
                )
                if status == 201:
                    return _LifecycleLock(work_item_id, owner, lock_sha)
                if status != 409:
                    raise WorkItemLifecycleError(
                        f"Unable to create lifecycle lock ref; HTTP {status}."
                    )
                continue

            current_sha, mode, current_owner, current_expiry = current
            if mode == "held":
                if current_expiry is None:
                    raise WorkItemLifecycleError("Held lifecycle lock has no expiry.")
                if current_expiry > datetime.now(timezone.utc):
                    raise WorkItemLifecycleError(
                        f"Lifecycle lock for #{work_item_id} is held by {current_owner} "
                        f"until {current_expiry.isoformat()}."
                    )

            new_sha = self._create_lifecycle_lock_commit(
                current_sha,
                work_item_id=work_item_id,
                mode="held",
                owner=owner,
                expires_at=expires_at,
            )
            status, _ = self._request(
                "PATCH",
                ref_path,
                {"sha": new_sha, "force": False},
            )
            if status == 200:
                return _LifecycleLock(work_item_id, owner, new_sha)
            if status != 409:
                raise WorkItemLifecycleError(
                    f"Unable to acquire lifecycle lock for #{work_item_id}; HTTP {status}."
                )

        raise WorkItemLifecycleError(
            f"Lifecycle lock for #{work_item_id} changed concurrently; refusing to overwrite."
        )

    def _release_lifecycle_lock(self, lock: _LifecycleLock) -> None:
        current = self._read_lifecycle_lock(lock.work_item_id)
        if current is None or current[0] != lock.ref_sha:
            raise WorkItemLifecycleError(
                f"Lifecycle lock for #{lock.work_item_id} was lost before release."
            )
        _, mode, owner, _ = current
        if mode != "held" or owner != lock.owner:
            raise WorkItemLifecycleError(
                f"Lifecycle lock for #{lock.work_item_id} is owned by another writer."
            )
        free_sha = self._create_lifecycle_lock_commit(
            lock.ref_sha,
            work_item_id=lock.work_item_id,
            mode="free",
            owner=lock.owner,
            expires_at=None,
        )
        status, _ = self._request(
            "PATCH",
            self._lifecycle_lock_ref_path(lock.work_item_id),
            {"sha": free_sha, "force": False},
        )
        if status != 200:
            raise WorkItemLifecycleError(
                f"Lifecycle lock for #{lock.work_item_id} changed before release; "
                "refusing to overwrite another writer's lock."
            )

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
    require_verified_mutation(
        evidence,
        f"Lifecycle {evidence.operation} mutation",
    )
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
