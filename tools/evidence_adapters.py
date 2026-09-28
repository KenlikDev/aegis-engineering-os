"""Adapt specialized readiness results into the canonical Aegis evidence envelope."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from evidence_contract import EvidenceContractError, EvidenceRecord, build_evidence
from promotion_readiness import PromotionReadiness
from release_readiness import ReleaseReadiness

if TYPE_CHECKING:
    from implementation_readiness import ImplementationReadiness
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

