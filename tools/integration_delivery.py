#!/usr/bin/env python3
"""Compose verified task PR delivery, exact-SHA validation, and integration merge."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from delivery import (
    CreatePullRequestRequest,
    DeliveryError,
    PullRequestProvider,
    create_review_pull_request,
)
from integration_merge import (
    INTEGRATION_BRANCH,
    IntegrationMergeError,
    IntegrationMergeProvider,
    sync_integration_merge,
)
from promotion_readiness import (
    DEFAULT_WORKFLOW,
    ValidationRun,
)
from work_item_lifecycle import (
    LifecycleState,
    WorkItemLifecycleError,
    WorkItemProvider,
)


class IntegrationDeliveryError(RuntimeError):
    """Raised when the composed integration-delivery workflow cannot proceed safely."""


class ValidationProvider(Protocol):
    """Provider-neutral exact-SHA validation lookup."""

    def latest_successful_validation(
        self,
        workflow: str,
        head_sha: str,
    ) -> ValidationRun | None: ...


@dataclass(frozen=True, slots=True)
class IntegrationDeliveryRequest:
    """Explicit task PR delivery request."""

    repository: str
    work_item_id: str
    head: str
    title: str
    body: str
    workflow: str = DEFAULT_WORKFLOW
    draft: bool = False


def deliver_to_integration(
    pr_provider: PullRequestProvider,
    merge_provider: IntegrationMergeProvider,
    validation_provider: ValidationProvider,
    work_item_provider: WorkItemProvider,
    request: IntegrationDeliveryRequest,
) -> dict[str, Any]:
    """Create/reuse, validate, merge, and synchronize one task into ai/integration."""
    if request.repository != merge_provider.repository:
        raise IntegrationDeliveryError(
            "Delivery providers must reference the same repository."
        )
    if request.repository != getattr(validation_provider, "repository", request.repository):
        raise IntegrationDeliveryError(
            "Validation provider must reference the same repository."
        )
    if request.workflow.strip() == "":
        raise IntegrationDeliveryError("Validation workflow must not be empty.")
    if request.draft:
        raise IntegrationDeliveryError(
            "The composed integration delivery workflow does not accept draft PRs."
        )

    try:
        item = work_item_provider.get(request.work_item_id)
    except WorkItemLifecycleError as exc:
        raise IntegrationDeliveryError(
            "Unable to read the work item before integration delivery."
        ) from exc

    if item.state != LifecycleState.REVIEW:
        raise IntegrationDeliveryError(
            "Integration delivery requires a work item in review state; "
            f"got {item.state.value}."
        )

    try:
        pr_result = create_review_pull_request(
            pr_provider,
            work_item_provider,
            request.work_item_id,
            CreatePullRequestRequest(
                repository=request.repository,
                head=request.head,
                base=INTEGRATION_BRANCH,
                title=request.title,
                body=request.body,
                draft=False,
            ),
        )
    except (DeliveryError, WorkItemLifecycleError) as exc:
        raise IntegrationDeliveryError(
            "Task pull-request preparation failed."
        ) from exc

    pull_request_number = pr_result["pull_request"]["number"]
    if not isinstance(pull_request_number, int) or pull_request_number <= 0:
        raise IntegrationDeliveryError(
            "Task pull-request preparation returned an invalid PR number."
        )

    pull_request = merge_provider.get_pull_request(pull_request_number)
    if pull_request.head != request.head:
        raise IntegrationDeliveryError(
            "Prepared pull request head does not match the requested task branch."
        )
    if pull_request.base != INTEGRATION_BRANCH:
        raise IntegrationDeliveryError(
            "Prepared pull request base does not match ai/integration."
        )
    if pull_request.draft:
        raise IntegrationDeliveryError(
            "Prepared pull request is a draft and cannot enter autonomous integration."
        )
    if pull_request.merged:
        validation = None
        try:
            merge_result = sync_integration_merge(
                merge_provider,
                work_item_provider,
                request.work_item_id,
                pull_request_number,
            )
        except IntegrationMergeError as exc:
            raise IntegrationDeliveryError(
                "Already-merged integration synchronization failed."
            ) from exc
    else:
        validation = validation_provider.latest_successful_validation(
            request.workflow,
            pull_request.head_sha,
        )
        if validation is None:
            raise IntegrationDeliveryError(
                "No successful Aegis Validation run exists for the exact task PR head SHA."
            )

        if pull_request.mergeable_state != "clean":
            raise IntegrationDeliveryError(
                "Task pull request mergeable_state must be clean before integration."
            )

        try:
            merge_result = sync_integration_merge(
                merge_provider,
                work_item_provider,
                request.work_item_id,
                pull_request_number,
                expected_head_sha=validation.head_sha,
            )
        except IntegrationMergeError as exc:
            raise IntegrationDeliveryError(
                "Integration merge failed after validation."
            ) from exc

    return {
        "status": merge_result["status"],
        "work_item_id": request.work_item_id,
        "pull_request": merge_result["pull_request"],
        "validation": (
            {
                "id": validation.id,
                "workflow": validation.workflow,
                "status": validation.status,
                "conclusion": validation.conclusion,
                "head_sha": validation.head_sha,
                "url": validation.url,
            }
            if validation
            else None
        ),
        "integration": merge_result.get("integration"),
        "traceability_verified": merge_result.get("traceability_verified"),
        "work_item": merge_result.get("work_item"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compose verified task delivery into ai/integration."
    )
    parser.add_argument("repository")
    parser.add_argument("work_item_id")
    parser.add_argument("head")
    parser.add_argument("title")
    parser.add_argument("--body", default="")
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument(
        "--canonical-evidence-output",
        type=Path,
        help="Optional canonical evidence-provenance output path.",
    )
    args = parser.parse_args()

    try:
        token = os.environ.get(args.token_env, "")
        pr_provider = _build_pr_provider(args.repository, token)
        merge_provider = _build_merge_provider(args.repository, token)
        validation_provider = _build_validation_provider(args.repository, token)
        work_item_provider = _build_work_item_provider(args.repository, token)

        result = deliver_to_integration(
            pr_provider,
            merge_provider,
            validation_provider,
            work_item_provider,
            IntegrationDeliveryRequest(
                repository=args.repository,
                work_item_id=args.work_item_id,
                head=args.head,
                title=args.title,
                body=args.body,
                workflow=args.workflow,
            ),
        )
    except (
        DeliveryError,
        IntegrationMergeError,
        IntegrationDeliveryError,
        WorkItemLifecycleError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    try:
        if args.canonical_evidence_output is not None:
            from evidence_adapters import integration_delivery_evidence

            canonical = integration_delivery_evidence(
                result,
                repository=args.repository,
                observed_at=datetime.now(timezone.utc),
            )
            write_evidence(
                canonical,
                args.canonical_evidence_output.expanduser().resolve(),
            )
    except (EvidenceContractError, OSError, ValueError, IntegrationDeliveryError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _build_pr_provider(repository: str, token: str) -> PullRequestProvider:
    from delivery import GitHubPullRequestProvider

    return GitHubPullRequestProvider(repository, token)


def _build_merge_provider(repository: str, token: str) -> IntegrationMergeProvider:
    from integration_merge import GitHubIntegrationMergeProvider

    return GitHubIntegrationMergeProvider(repository, token)


def _build_validation_provider(repository: str, token: str) -> ValidationProvider:
    from promotion_readiness import GitHubPromotionProvider

    return GitHubPromotionProvider(repository, token)


def _build_work_item_provider(repository: str, token: str) -> WorkItemProvider:
    from work_item_lifecycle import GitHubIssuesProvider

    return GitHubIssuesProvider(repository, token)


if __name__ == "__main__":
    raise SystemExit(main())
