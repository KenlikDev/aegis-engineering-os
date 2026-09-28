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
    from ci_diagnosis import DiagnosticReport
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

