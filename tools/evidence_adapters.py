"""Adapt specialized readiness results into the canonical Aegis evidence envelope."""

from __future__ import annotations

from datetime import datetime
import re
from typing import TYPE_CHECKING, Any, Mapping

from evidence_contract import EvidenceContractError, EvidenceRecord, build_evidence
from promotion_readiness import PromotionReadiness
from release_readiness import ReleaseReadiness

_CANONICAL_SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)


def _canonical_safe(value: Any) -> Any:
    """Remove secret-like mapping keys before evidence-contract validation."""
    if isinstance(value, Mapping):
        return {
            key: _canonical_safe(item)
            for key, item in value.items()
            if isinstance(key, str) and not _CANONICAL_SENSITIVE_KEY_RE.search(key)
        }
    if isinstance(value, list):
        return [_canonical_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_safe(item) for item in value]
    return value


if TYPE_CHECKING:
    from architecture_planning import ArchitecturePlan
    from ci_diagnosis import DiagnosticReport
    from requirements_clarification import RequirementsReport
    from workflow_composition import WorkflowComposition
    from knowledge_gap import KnowledgeGapRecord
    from work_item_lifecycle import MutationEvidence
    from openhands_execution import OpenHandsExecutionResult
    from implementation_readiness import ImplementationReadiness
    from security_review import SecurityReviewResult
    from version_verification import VersionEvidence


def _timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise EvidenceContractError("observed_at datetime must include a timezone.")
        return value.isoformat(timespec="seconds")
    if isinstance(value, str):
        return value
    raise EvidenceContractError("observed_at must be an ISO-8601 string or timezone-aware datetime.")


def _repository_reference(repository: str) -> str:
    return f"https://github.com/{repository}"


def promotion_sync_evidence(
    result: Mapping[str, Any],
    *,
    repository: str,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a human-controlled promotion synchronization result into canonical provenance."""
    status = result.get("status")
    if status == "not-merged":
        canonical_status = "unknown"
        uncertainty = ["The promotion pull request was not merged into the selected target."]
    elif status == "verified":
        canonical_status = "verified"
        uncertainty = []
    else:
        raise EvidenceContractError(
            f"Unsupported promotion synchronization status: {status!r}."
        )

    work_item_id = result.get("work_item_id")
    target_branch = result.get("target_branch")
    pull_request = result.get("pull_request")
    target = result.get("target")
    work_item = result.get("work_item")

    if not isinstance(work_item_id, str) or not work_item_id:
        raise EvidenceContractError("Promotion synchronization work_item_id is required.")
    if not isinstance(target_branch, str) or target_branch not in {"develop", "main"}:
        raise EvidenceContractError(
            "Promotion synchronization target_branch must be develop or main."
        )
    if not isinstance(pull_request, Mapping):
        raise EvidenceContractError(
            "Promotion synchronization pull_request result is malformed."
        )

    if canonical_status == "unknown":
        return build_evidence(
            {
                "schema_version": 1,
                "kind": "promotion-sync",
                "source": f"github:{repository}",
                "subject": f"promotion:{work_item_id}->{target_branch}",
                "revision": None,
                "observed_at": _timestamp(observed_at),
                "status": "unknown",
                "result": _canonical_safe(dict(result)),
                "uncertainty": uncertainty,
                "references": (
                    [pull_request["url"]]
                    if isinstance(pull_request.get("url"), str)
                    and pull_request.get("url").startswith("https://")
                    else []
                ),
                "artifact_sha256": None,
            }
        )

    if not isinstance(target, Mapping):
        raise EvidenceContractError(
            "Verified promotion synchronization requires target evidence."
        )
    if not isinstance(work_item, Mapping):
        raise EvidenceContractError(
            "Verified promotion synchronization requires work-item evidence."
        )

    merge_sha = pull_request.get("merge_commit_sha")
    target_sha = target.get("sha")
    if (
        not isinstance(merge_sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", merge_sha)
        or not isinstance(target_sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", target_sha)
    ):
        raise EvidenceContractError(
            "Promotion synchronization merge and target SHAs must be valid 40-character hexadecimal revisions."
        )
    if merge_sha != target_sha:
        raise EvidenceContractError(
            "Promotion synchronization merge commit does not match the protected target SHA."
        )
    if target.get("branch") != target_branch or target.get("protected") is not True:
        raise EvidenceContractError(
            "Promotion synchronization target identity or protection state is invalid."
        )
    if pull_request.get("base") != target_branch or pull_request.get("merged") is not True:
        raise EvidenceContractError(
            "Promotion synchronization pull request does not describe the verified promotion merge."
        )
    if (
        pull_request.get("head_repository") != repository
        or pull_request.get("base_repository") != repository
    ):
        raise EvidenceContractError(
            "Promotion synchronization pull-request repositories must match the configured repository."
        )
    if result.get("traceability_verified") is not True:
        raise EvidenceContractError(
            "Promotion synchronization traceability is not read-after-write verified."
        )
    if work_item.get("transition_verified") is not True:
        raise EvidenceContractError(
            "Promotion synchronization lifecycle transition is not read-after-write verified."
        )

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "promotion-sync",
            "source": f"github:{repository}",
            "subject": f"promotion:{work_item_id}->{target_branch}",
            "revision": target_sha,
            "observed_at": _timestamp(observed_at),
            "status": "verified",
            "result": _canonical_safe(dict(result)),
            "uncertainty": [],
            "references": (
                [pull_request["url"]]
                if isinstance(pull_request.get("url"), str)
                and pull_request.get("url").startswith("https://")
                else []
            ),
            "artifact_sha256": None,
        }
    )


def integration_delivery_evidence(
    result: Mapping[str, Any],
    *,
    repository: str,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a completed integration-delivery composition into canonical provenance."""
    status = result.get("status")
    if status == "not-merged":
        canonical_status = "unknown"
        uncertainty = ["The composed integration delivery did not produce a merged PR."]
    elif status == "verified":
        canonical_status = "verified"
        uncertainty = []
    else:
        raise EvidenceContractError(
            f"Unsupported integration delivery status: {status!r}."
        )

    work_item_id = result.get("work_item_id")
    if not isinstance(work_item_id, str) or not work_item_id:
        raise EvidenceContractError("Integration delivery work_item_id is required.")

    pull_request = result.get("pull_request")
    validation = result.get("validation")
    integration = result.get("integration")
    work_item = result.get("work_item")

    for field, value in (
        ("pull_request", pull_request),
        ("integration", integration),
        ("work_item", work_item),
    ):
        if not isinstance(value, Mapping):
            raise EvidenceContractError(
                f"Integration delivery {field} result is required for verified status."
            )
    if validation is not None and not isinstance(validation, Mapping):
        raise EvidenceContractError("Integration delivery validation result is malformed.")

    revision: str | None = None
    if canonical_status == "verified":
        assert isinstance(pull_request, Mapping)
        assert isinstance(integration, Mapping)
        assert isinstance(work_item, Mapping)

        validation_head = validation.get("head_sha") if isinstance(validation, Mapping) else None
        pr_head = pull_request.get("head_sha")
        merge_sha = pull_request.get("merge_commit_sha")
        integration_sha = integration.get("sha")
        transition_verified = work_item.get("transition_verified")

        for field, value in (
            ("pull-request head SHA", pr_head),
            ("merge commit SHA", merge_sha),
            ("integration SHA", integration_sha),
        ):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
                raise EvidenceContractError(
                    f"Integration delivery {field} must be a 40-character hexadecimal SHA."
                )

        if validation is not None:
            if not isinstance(validation_head, str) or not re.fullmatch(
                r"[0-9a-f]{40}", validation_head
            ):
                raise EvidenceContractError(
                    "Integration delivery validation head SHA must be a 40-character hexadecimal SHA."
                )
            if validation_head != pr_head:
                raise EvidenceContractError(
                    "Integration delivery validation head does not match the PR head."
                )
            if validation.get("status") != "completed" or validation.get("conclusion") != "success":
                raise EvidenceContractError(
                    "Integration delivery validation must be a completed successful run."
                )
        else:
            uncertainty.append(
                "No new validation run was performed during already-merged integration synchronization."
            )

        if pull_request.get("merged") is not True:
            raise EvidenceContractError(
                "Verified integration delivery must describe a merged pull request."
            )
        if pull_request.get("base") != "ai/integration":
            raise EvidenceContractError(
                "Integration delivery pull request base must be ai/integration."
            )
        if merge_sha != integration_sha:
            raise EvidenceContractError(
                "Integration delivery merge commit does not match the post-merge integration SHA."
            )
        if result.get("traceability_verified") is not True:
            raise EvidenceContractError(
                "Integration delivery traceability must be read-after-write verified."
            )
        if transition_verified is not True:
            raise EvidenceContractError(
                "Integration delivery lifecycle transition must be read-after-write verified."
            )
        revision = merge_sha

    pull_request_payload = {
        "number": pull_request.get("number"),
        "url": pull_request.get("url"),
        "head": pull_request.get("head"),
        "head_repository": pull_request.get("head_repository"),
        "head_sha": pull_request.get("head_sha"),
        "base": pull_request.get("base"),
        "base_repository": pull_request.get("base_repository"),
        "merged": pull_request.get("merged"),
        "merge_commit_sha": pull_request.get("merge_commit_sha"),
    }
    validation_payload = (
        {
            "id": validation.get("id"),
            "workflow": validation.get("workflow"),
            "status": validation.get("status"),
            "conclusion": validation.get("conclusion"),
            "head_sha": validation.get("head_sha"),
            "url": validation.get("url"),
        }
        if isinstance(validation, Mapping)
        else None
    )
    integration_payload = {
        "branch": integration.get("branch"),
        "sha": integration.get("sha"),
        "protected": integration.get("protected"),
    }
    work_item_payload = {
        "state_after": work_item.get("state_after"),
        "transition_verified": work_item.get("transition_verified"),
    }

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "integration-delivery",
            "source": f"github:{repository}",
            "subject": f"work-item:{work_item_id}",
            "revision": revision,
            "observed_at": _timestamp(observed_at),
            "status": canonical_status,
            "result": {
                "work_item_id": work_item_id,
                "pull_request": pull_request_payload,
                "validation": validation_payload,
                "integration": integration_payload,
                "work_item": work_item_payload,
                "traceability_verified": result.get("traceability_verified"),
            },
            "uncertainty": uncertainty,
            "references": (
                [pull_request.get("url")]
                if isinstance(pull_request.get("url"), str)
                and pull_request.get("url").startswith("https://")
                else []
            ),
            "artifact_sha256": None,
        }
    )

def runtime_preflight_evidence(
    result: Mapping[str, Any],
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a successful local runtime preflight into canonical provenance."""
    if result.get("status") != "verified":
        raise EvidenceContractError(
            "Runtime preflight evidence requires a successful verified preflight result."
        )

    profile_name = result.get("profile_name")
    provider = result.get("provider")
    surface = result.get("surface")
    integration = result.get("integration")
    connection_mode = result.get("connection_mode")
    model = result.get("model")
    ollama_base_url = result.get("ollama_base_url")
    ollama_version = result.get("ollama_version")

    required_strings = {
        "profile_name": profile_name,
        "provider": provider,
        "surface": surface,
        "integration": integration,
        "connection_mode": connection_mode,
        "model": model,
        "ollama_base_url": ollama_base_url,
        "ollama_version": ollama_version,
    }
    for field, value in required_strings.items():
        if not isinstance(value, str) or not value.strip():
            raise EvidenceContractError(
                f"Runtime preflight {field} must be a non-empty string."
            )

    if result.get("model_available") is not True:
        raise EvidenceContractError(
            "Runtime preflight canonical evidence requires an exact installed model."
        )

    agent_server = result.get("openhands_agent_server")
    if agent_server is not None and not isinstance(agent_server, Mapping):
        raise EvidenceContractError(
            "Runtime preflight OpenHands Agent Server result is malformed."
        )

    agent_payload: dict[str, Any] | None = None
    revision: str | None = None
    if agent_server is not None:
        server_status = agent_server.get("status")
        if server_status != "verified":
            raise EvidenceContractError(
                "Runtime preflight Agent Server result must be verified when present."
            )
        agent_fields = {
            "active_llm_model": agent_server.get("active_llm_model"),
            "llm_base_url": agent_server.get("llm_base_url"),
            "base_url": agent_server.get("base_url"),
            "version": agent_server.get("version"),
            "sdk_version": agent_server.get("sdk_version"),
            "tools_version": agent_server.get("tools_version"),
            "workspace_version": agent_server.get("workspace_version"),
            "conversation_runtime": agent_server.get("conversation_runtime"),
        }
        for field, value in agent_fields.items():
            if not isinstance(value, str) or not value.strip():
                raise EvidenceContractError(
                    f"Runtime preflight Agent Server {field} must be a non-empty string."
                )

        credentials_configured = agent_server.get("llm_api_key_is_set")
        if credentials_configured is not True:
            raise EvidenceContractError(
                "Runtime preflight Agent Server credentials state must be true."
            )

        build_sha = agent_server.get("build_git_sha")
        if isinstance(build_sha, str) and re.fullmatch(r"[0-9a-f]{40}", build_sha):
            revision = build_sha

        agent_payload = {
            "active_llm_model": agent_fields["active_llm_model"],
            "llm_base_url": agent_fields["llm_base_url"],
            "base_url": agent_fields["base_url"],
            "version": agent_fields["version"],
            "sdk_version": agent_fields["sdk_version"],
            "tools_version": agent_fields["tools_version"],
            "workspace_version": agent_fields["workspace_version"],
            "conversation_runtime": agent_fields["conversation_runtime"],
            "build_git_sha": build_sha if isinstance(build_sha, str) else None,
            "build_git_ref": (
                agent_server.get("build_git_ref")
                if isinstance(agent_server.get("build_git_ref"), str)
                else None
            ),
            "llm_auth_configured": True,
        }

    payload = {
        "schema_version": 1,
        "kind": "runtime-preflight",
        "source": "aegis:runtime-preflight",
        "subject": f"profile:{profile_name}",
        "revision": revision,
        "observed_at": _timestamp(observed_at),
        "status": "verified",
        "result": {
            "profile_name": profile_name,
            "provider": provider,
            "surface": surface,
            "integration": integration,
            "connection_mode": connection_mode,
            "model": model,
            "ollama_base_url": ollama_base_url,
            "ollama_version": ollama_version,
            "model_available": result.get("model_available") is True,
            "openhands_agent_server": agent_payload,
        },
        "uncertainty": [],
        "references": [],
        "artifact_sha256": None,
    }
    return build_evidence(payload)


def promotion_readiness_evidence(
    result: PromotionReadiness,
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a promotion-readiness result without changing its original schema."""
    validation = result.validation
    validation_payload: dict[str, Any] | None = None
    uncertainty: list[str] = []

    if validation is not None:
        validation_payload = {
            "id": validation.id,
            "workflow": validation.workflow,
            "status": validation.status,
            "conclusion": validation.conclusion,
            "head_sha": validation.head_sha,
            "validated_sha": validation.validated_sha,
            "evidence_type": validation.evidence_type,
            "pull_request_number": validation.pull_request_number,
            "url": validation.url,
        }
        if validation.evidence_type == "merged-pull-request":
            uncertainty.append(
                "CI evidence uses merged-pull-request validation fallback rather than direct branch-push validation."
            )

    if not result.compare.changed_files_complete:
        uncertainty.append(
            "GitHub compare reported an incomplete changed-file list."
        )

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "promotion-readiness",
            "source": f"github:{result.repository}",
            "subject": f"promotion:{result.source.branch}->{result.target.branch}",
            "revision": result.source.sha,
            "observed_at": _timestamp(observed_at),
            "status": "verified" if result.ready else "failed",
            "result": {
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
                "validation": validation_payload,
                "blockers": list(result.blockers),
            },
            "uncertainty": uncertainty,
            "references": [
                *(
                    [validation.url]
                    if validation is not None and validation.url
                    else []
                ),
                _repository_reference(result.repository),
            ],
            "artifact_sha256": None,
        }
    )


def release_readiness_evidence(
    result: ReleaseReadiness,
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a release-readiness result without changing its original schema."""
    validation = result.validation
    validation_payload: dict[str, Any] | None = None

    if validation is not None:
        validation_payload = {
            "id": validation.id,
            "workflow": validation.workflow,
            "status": validation.status,
            "conclusion": validation.conclusion,
            "head_sha": validation.head_sha,
            "url": validation.url,
        }

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "release-readiness",
            "source": f"github:{result.repository}",
            "subject": f"release:{result.target.branch}",
            "revision": result.target.sha,
            "observed_at": _timestamp(observed_at),
            "status": "verified" if result.ready else "failed",
            "result": {
                "target": {
                    "branch": result.target.branch,
                    "sha": result.target.sha,
                    "protected": result.target.protected,
                },
                "validation": validation_payload,
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
            },
            "uncertainty": [],
            "references": [
                *(
                    [validation.url]
                    if validation is not None and validation.url
                    else []
                ),
                _repository_reference(result.repository),
            ],
            "artifact_sha256": None,
        }
    )

def integration_merge_evidence(
    result: Mapping[str, Any],
    *,
    repository: str,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert an integration-merge result into canonical provenance evidence."""
    status = result.get("status")
    if status == "verified":
        canonical_status = "verified"
        uncertainty: list[str] = []
    elif status == "not-merged":
        canonical_status = "unknown"
        uncertainty = ["The integration pull request was not merged."]
    else:
        raise EvidenceContractError(
            f"Unsupported integration merge status: {status!r}."
        )

    work_item_id = result.get("work_item_id")
    if not isinstance(work_item_id, str) or not work_item_id:
        raise EvidenceContractError("Integration merge work_item_id is required.")

    pull_request = result.get("pull_request")
    integration = result.get("integration")
    work_item = result.get("work_item")
    if not isinstance(pull_request, Mapping):
        raise EvidenceContractError("Integration merge pull_request result is malformed.")
    if (
        pull_request.get("head_repository") != repository
        or pull_request.get("base_repository") != repository
    ):
        raise EvidenceContractError(
            "Integration merge pull-request repositories must match the configured repository."
        )
    if not isinstance(integration, Mapping):
        raise EvidenceContractError("Integration merge integration result is malformed.")
    if not isinstance(work_item, Mapping):
        raise EvidenceContractError("Integration merge work_item result is malformed.")

    revision = integration.get("sha") if canonical_status == "verified" else None
    if revision is not None and (
        not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)
    ):
        raise EvidenceContractError(
            "Integration merge integration SHA must be a 40-character hexadecimal revision."
        )

    pull_request_url = pull_request.get("url")
    if not isinstance(pull_request_url, str) or not pull_request_url.startswith(
        "https://"
    ):
        raise EvidenceContractError(
            "Integration merge pull-request URL must be HTTPS."
        )

    safe_result = _canonical_safe(dict(result))
    return build_evidence(
        {
            "schema_version": 1,
            "kind": "integration-merge",
            "source": f"github:{repository}",
            "subject": f"work-item:{work_item_id}",
            "revision": revision,
            "observed_at": _timestamp(observed_at),
            "status": canonical_status,
            "result": safe_result,
            "uncertainty": uncertainty,
            "references": [pull_request_url, _repository_reference(repository)],
            "artifact_sha256": None,
        }
    )


def version_verification_evidence(
    evidence: VersionEvidence,
    *,
    observed_at: datetime | str,
    revision: str | None = None,
) -> EvidenceRecord:
    """Convert source-pinned version evidence into the canonical envelope."""
    uncertainty: list[str] = []
    if evidence.external_verification_pending:
        uncertainty.append(
            "External compatibility verification remains pending for the recorded version claims."
        )

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "version-verification",
            "source": "aegis:version-verification",
            "subject": "project-version-inventory",
            "revision": revision,
            "observed_at": _timestamp(observed_at),
            "status": (
                "pending" if evidence.external_verification_pending else "verified"
            ),
            "result": {
                "schema_version": evidence.schema_version,
                "claims": [
                    {
                        "component": claim.component,
                        "version": claim.version,
                        "scope": claim.scope,
                        "source": claim.source,
                        "source_sha256": claim.source_sha256,
                    }
                    for claim in evidence.claims
                ],
                "external_verification_pending": (
                    evidence.external_verification_pending
                ),
            },
            "uncertainty": uncertainty,
            "references": [],
            "artifact_sha256": None,
        }
    )

def implementation_readiness_evidence(
    result: "ImplementationReadiness",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert implementation readiness into canonical evidence without changing its gate semantics."""
    if result.ready:
        status = "pending" if result.version_external_verification_pending else "verified"
    else:
        status = "failed"

    uncertainty: list[str] = []
    if result.version_external_verification_pending:
        uncertainty.append(
            "External compatibility verification remains pending in implementation readiness."
        )

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "implementation-readiness",
            "source": "aegis:implementation-readiness",
            "subject": (
                f"work-item:{result.work_item_id}"
                if result.work_item_id is not None
                else "work-item:unspecified"
            ),
            "revision": None,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "work_item_path": result.work_item_path,
                "work_item_id": result.work_item_id,
                "work_item_kind": result.work_item_kind,
                "lifecycle_state": result.lifecycle_state,
                "requirements_status": result.requirements_status,
                "architecture_required": result.architecture_required,
                "version_evidence_ref": result.version_evidence_ref,
                "version_external_verification_pending": (
                    result.version_external_verification_pending
                ),
                "observations": [
                    {
                        "check": observation.check,
                        "status": observation.status,
                        "detail": observation.detail,
                    }
                    for observation in result.observations
                ],
                "blockers": list(result.blockers),
                "composition_steps": list(result.composition_steps),
                "evidence_set": (
                    {
                        "status": result.evidence_set.status,
                        "bundle_id": result.evidence_set.bundle_id,
                        "requirements_ref": result.evidence_set.requirements_ref,
                        "requirements_satisfied": result.evidence_set.requirements_satisfied,
                        "requirements_total": result.evidence_set.requirements_total,
                        "detail": result.evidence_set.detail,
                    }
                    if result.evidence_set is not None
                    else None
                ),
            },
            "uncertainty": uncertainty,
            "references": [],
            "artifact_sha256": None,
        }
    )

def testing_evidence(
    result: Mapping[str, Any],
    *,
    observed_at: datetime | str,
    revision: str | None = None,
) -> EvidenceRecord:
    """Convert the already-redacted testing result into canonical evidence."""
    status = result.get("status")
    if status not in {"verified", "failed"}:
        raise EvidenceContractError(
            "Testing result status must be 'verified' or 'failed'."
        )

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "testing",
            "source": "aegis:testing",
            "subject": "project-testing",
            "revision": revision,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": dict(result),
            "uncertainty": [],
            "references": [],
            "artifact_sha256": None,
        }
    )

def security_review_evidence(
    result: "SecurityReviewResult",
    *,
    observed_at: datetime | str,
    revision: str | None = None,
) -> EvidenceRecord:
    """Convert a deterministic security-review result into canonical evidence."""
    status = "failed" if any(finding.severity == "high" for finding in result.findings) else "verified"
    return build_evidence(
        {
            "schema_version": 1,
            "kind": "security-review",
            "source": "aegis:security-review",
            "subject": "repository-security",
            "revision": revision,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "root": result.root,
                "status": result.status,
                "findings": [
                    {
                        "rule_id": finding.rule_id,
                        "severity": finding.severity,
                        "path": finding.path,
                        "message": finding.message,
                        "line": finding.line,
                    }
                    for finding in result.findings
                ],
                "summary": {
                    "high": sum(f.severity == "high" for f in result.findings),
                    "medium": sum(f.severity == "medium" for f in result.findings),
                    "low": sum(f.severity == "low" for f in result.findings),
                },
            },
            "uncertainty": [],
            "references": [],
            "artifact_sha256": None,
        }
    )

def ci_diagnosis_evidence(
    report: "DiagnosticReport",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a read-only CI diagnosis into canonical provenance evidence."""
    if report.status == "healthy":
        status = "verified"
        uncertainty: list[str] = []
    elif report.status == "diagnosed":
        status = "failed"
        uncertainty = []
    elif report.status == "inconclusive":
        status = "unknown"
        uncertainty = [
            "No supported deterministic failure signature was established; remediation must not assume a root cause."
        ]
    else:
        raise EvidenceContractError(
            f"Unsupported CI diagnosis status: {report.status!r}."
        )

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "ci-diagnosis",
            "source": f"github:{report.run.repository}",
            "subject": f"workflow-run:{report.run.run_id}",
            "revision": report.run.head_sha,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "run": {
                    "repository": report.run.repository,
                    "run_id": report.run.run_id,
                    "name": report.run.name,
                    "workflow_path": report.run.workflow_path,
                    "event": report.run.event,
                    "status": report.run.status,
                    "conclusion": report.run.conclusion,
                    "head_branch": report.run.head_branch,
                    "head_sha": report.run.head_sha,
                    "url": report.run.url,
                },
                "jobs": [
                    {
                        "job_id": job.job_id,
                        "name": job.name,
                        "status": job.status,
                        "conclusion": job.conclusion,
                        "url": job.url,
                        "failed_steps": list(job.failed_steps),
                    }
                    for job in report.jobs
                ],
                "findings": [
                    {
                        "category": finding.category,
                        "severity": finding.severity,
                        "actionable": finding.actionable,
                        "job_id": finding.job_id,
                        "job": finding.job,
                        "step": finding.step,
                        "message": finding.message,
                        "evidence": finding.evidence,
                    }
                    for finding in report.findings
                ],
                "status": report.status,
                "actionable": report.actionable,
                "summary": {
                    "actionable": sum(
                        finding.actionable for finding in report.findings
                    ),
                    "high": sum(
                        finding.severity == "high" for finding in report.findings
                    ),
                    "medium": sum(
                        finding.severity == "medium" for finding in report.findings
                    ),
                    "low": sum(
                        finding.severity == "low" for finding in report.findings
                    ),
                },
            },
            "uncertainty": uncertainty,
            "references": [report.run.url],
            "artifact_sha256": None,
        }
    )

def openhands_execution_evidence(
    result: "OpenHandsExecutionResult",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a redacted OpenHands execution result into canonical evidence."""
    if result.outcome == "finished":
        status = "verified"
        uncertainty: list[str] = []
    elif result.outcome in {"error", "stuck", "blocked"}:
        status = "failed"
        uncertainty = [
            f"OpenHands execution ended without successful completion: {result.outcome}."
        ]
    else:
        raise EvidenceContractError(
            f"Unsupported OpenHands execution outcome: {result.outcome!r}."
        )

    safe_state = _canonical_safe(result.state)
    safe_events = _canonical_safe(list(result.events))

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "openhands-execution",
            "source": "aegis:openhands-execution",
            "subject": f"conversation:{result.conversation_id}",
            "revision": None,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "conversation_id": result.conversation_id,
                "execution_status": result.execution_status,
                "outcome": result.outcome,
                "state": safe_state,
                "events": safe_events,
                "event_count": len(result.events),
            },
            "uncertainty": uncertainty,
            "references": [],
            "artifact_sha256": None,
        }
    )

def mutation_evidence(
    evidence: "MutationEvidence",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a lifecycle mutation result into canonical provenance evidence."""
    if not evidence.verified:
        status = "unknown"
        uncertainty = [
            "The provider mutation result was not read-after-write verified."
        ]
    else:
        status = "verified"
        uncertainty = []

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "work-item-mutation",
            "source": f"work-item-provider:{evidence.provider}",
            "subject": f"work-item:{evidence.work_item_id}",
            "revision": None,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "provider": evidence.provider,
                "operation": evidence.operation,
                "work_item_id": evidence.work_item_id,
                "state_before": evidence.state_before,
                "state_after": evidence.state_after,
                "verified": evidence.verified,
                "reference": evidence.reference,
                "identifier": evidence.identifier,
            },
            "uncertainty": uncertainty,
            "references": (
                [evidence.reference]
                if evidence.reference is not None
                else []
            ),
            "artifact_sha256": None,
        }
    )

def knowledge_gap_evidence(
    record: "KnowledgeGapRecord",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert a knowledge-gap record into canonical evidence without activating knowledge."""
    if record.state == "candidate":
        status = "pending"
        uncertainty = [
            "Knowledge-gap candidate has not completed focused validation."
        ]
    elif record.state == "validated":
        status = "verified"
        uncertainty = []
    elif record.state == "rejected":
        status = "failed"
        uncertainty = [
            "Knowledge-gap candidate was explicitly rejected and must not be treated as active guidance."
        ]
    else:
        raise EvidenceContractError(
            f"Unsupported knowledge-gap state: {record.state!r}."
        )

    validation = _canonical_safe(record.validation)
    transitions = _canonical_safe(list(record.transitions))

    references = list(record.candidate.references)
    if isinstance(validation, Mapping):
        raw_refs = validation.get("evidence_refs")
        if isinstance(raw_refs, list):
            references.extend(
                item
                for item in raw_refs
                if isinstance(item, str)
            )

    return build_evidence(
        {
            "schema_version": 1,
            "kind": "knowledge-gap",
            "source": "aegis:knowledge-gap-registry",
            "subject": f"candidate:{record.candidate.candidate_id}",
            "revision": record.candidate.candidate_sha256,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "state": record.state,
                "candidate": {
                    "candidate_id": record.candidate.candidate_id,
                    "scope": record.candidate.scope,
                    "capability": record.candidate.capability,
                    "problem": record.candidate.problem,
                    "proposed_change": record.candidate.proposed_change,
                    "references": list(record.candidate.references),
                    "created_at": record.candidate.created_at,
                    "candidate_sha256": record.candidate.candidate_sha256,
                },
                "validation": validation,
                "transitions": transitions,
            },
            "uncertainty": uncertainty,
            "references": references,
            "artifact_sha256": None,
        }
    )

def requirements_clarification_evidence(
    report: "RequirementsReport",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert deterministic requirements clarification into canonical evidence."""
    status = "verified" if report.ready else "failed"
    return build_evidence(
        {
            "schema_version": 1,
            "kind": "requirements-clarification",
            "source": "aegis:requirements-clarification",
            "subject": f"work-item-document:{report.path}",
            "revision": None,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "path": report.path,
                "status": report.status,
                "ready": report.ready,
                "questions": [
                    {
                        "question_id": question.question_id,
                        "severity": question.severity,
                        "section": question.section,
                        "question": question.question,
                        "evidence": question.evidence,
                    }
                    for question in report.questions
                ],
                "summary": {
                    "blockers": sum(
                        question.severity == "blocker"
                        for question in report.questions
                    ),
                    "warnings": sum(
                        question.severity == "warning"
                        for question in report.questions
                    ),
                },
            },
            "uncertainty": [],
            "references": [],
            "artifact_sha256": None,
        }
    )


def workflow_composition_evidence(
    composition: "WorkflowComposition",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert an explicit workflow composition into canonical evidence."""
    return build_evidence(
        {
            "schema_version": 1,
            "kind": "workflow-composition",
            "source": "aegis:workflow-composition",
            "subject": f"work-item-kind:{composition.work_item_kind}",
            "revision": None,
            "observed_at": _timestamp(observed_at),
            "status": "verified",
            "result": {
                "work_item_kind": composition.work_item_kind,
                "steps": [
                    {
                        "name": step.name,
                        "kind": step.kind,
                        "required": step.required,
                        "condition": step.condition,
                    }
                    for step in composition.steps
                ],
                "required_steps": [
                    step.name for step in composition.required_steps
                ],
            },
            "uncertainty": [],
            "references": [],
            "artifact_sha256": None,
        }
    )


def architecture_planning_evidence(
    plan: "ArchitecturePlan",
    *,
    observed_at: datetime | str,
) -> EvidenceRecord:
    """Convert architecture planning into canonical evidence without collapsing its information classes."""
    status = "verified" if plan.ready else "failed"
    return build_evidence(
        {
            "schema_version": 1,
            "kind": "architecture-planning",
            "source": "aegis:architecture-planning",
            "subject": (
                f"work-item:{plan.work_item_id}"
                if plan.work_item_id is not None
                else f"work-item-document:{plan.path}"
            ),
            "revision": None,
            "observed_at": _timestamp(observed_at),
            "status": status,
            "result": {
                "path": plan.path,
                "work_item_id": plan.work_item_id,
                "lifecycle_state": plan.lifecycle_state,
                "status": plan.status,
                "requirements_status": plan.requirements_status,
                "evidence": [
                    {
                        "evidence_id": item.evidence_id,
                        "source": item.source,
                        "value": item.value,
                    }
                    for item in plan.evidence
                ],
                "deductions": [
                    {
                        "deduction_id": item.deduction_id,
                        "basis": item.basis,
                        "conclusion": item.conclusion,
                    }
                    for item in plan.deductions
                ],
                "constraints": list(plan.constraints),
                "boundaries": list(plan.boundaries),
                "affected_components": list(plan.affected_components),
                "adr_needs": list(plan.adr_needs),
                "non_goals": list(plan.non_goals),
                "user_owned_decisions": [
                    {
                        "question_id": item.question_id,
                        "ownership": item.ownership,
                        "question": item.question,
                        "basis": item.basis,
                    }
                    for item in plan.user_owned_decisions
                ],
                "blockers": [
                    {
                        "question_id": item.question_id,
                        "ownership": item.ownership,
                        "question": item.question,
                        "basis": item.basis,
                    }
                    for item in plan.blockers
                ],
            },
            "uncertainty": [],
            "references": [],
            "artifact_sha256": None,
        }
    )

