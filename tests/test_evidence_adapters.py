import sys
import unittest
from datetime import datetime, timezone

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_adapters import (  # noqa: E402
    architecture_planning_evidence,
    ci_diagnosis_evidence,
    implementation_readiness_evidence,
    integration_merge_evidence,
    knowledge_gap_evidence,
    mutation_evidence,
    promotion_readiness_evidence,
    openhands_execution_evidence,
    release_readiness_evidence,
    runtime_preflight_evidence,
    requirements_clarification_evidence,
    security_review_evidence,
    testing_evidence,
    version_verification_evidence,
    workflow_composition_evidence,
)
from evidence_contract import (  # noqa: E402
    EvidenceContractError,
    read_and_validate_evidence,
    write_evidence,
)
from ci_diagnosis import (  # noqa: E402
    DiagnosticFinding,
    DiagnosticReport,
    JobSnapshot,
    WorkflowRunSnapshot,
)
from promotion_readiness import BranchSnapshot, CompareSnapshot, PromotionReadiness, ValidationRun  # noqa: E402
from openhands_execution import OpenHandsExecutionResult  # noqa: E402
from implementation_readiness import (  # noqa: E402
    EvidenceSetReadiness,
    ImplementationReadiness,
    ReadinessObservation,
)
from security_review import SecurityFinding, SecurityReviewResult  # noqa: E402
from work_item_lifecycle import MutationEvidence  # noqa: E402
from architecture_planning import (  # noqa: E402
    ArchitectureDeduction,
    ArchitectureEvidence,
    ArchitecturePlan,
    ArchitectureQuestion,
)
from requirements_clarification import ClarificationQuestion, RequirementsReport  # noqa: E402
from workflow_composition import WorkflowComposition, WorkflowStep  # noqa: E402
from knowledge_gap import (  # noqa: E402
    create_candidate,
    reject_candidate,
    validate_candidate,
)
from release_readiness import ChangelogSnapshot, ReleaseReadiness  # noqa: E402
from version_verification import VersionClaim, VersionEvidence  # noqa: E402



REPOSITORY = "KenlikDev/aegis-engineering-os"
SOURCE_SHA = "1111111111111111111111111111111111111111"
TARGET_SHA = "2222222222222222222222222222222222222222"


class EvidenceAdapterTests(unittest.TestCase):
    def test_runtime_preflight_without_agent_server_is_verified(self):
        result = {
            "status": "verified",
            "profile_name": "development-local",
            "provider": "ollama",
            "surface": "local",
            "integration": "openhands_llm_ollama",
            "connection_mode": "local",
            "model": "gemma4:31b",
            "ollama_base_url": "http://127.0.0.1:11434",
            "ollama_version": "0.12.0",
            "model_available": True,
        }

        canonical = runtime_preflight_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual("runtime-preflight", canonical.kind)
        self.assertEqual("profile:development-local", canonical.subject)
        self.assertIsNone(canonical.revision)
        self.assertEqual("gemma4:31b", canonical.result["model"])
        self.assertIsNone(canonical.result["openhands_agent_server"])

    def test_runtime_preflight_preserves_agent_server_identity_without_secret(self):
        result = {
            "status": "verified",
            "profile_name": "development-local",
            "provider": "ollama",
            "surface": "local",
            "integration": "openhands_llm_ollama",
            "connection_mode": "local",
            "model": "gemma4:31b",
            "ollama_base_url": "http://127.0.0.1:11434",
            "ollama_version": "0.12.0",
            "model_available": True,
            "openhands_agent_server": {
                "status": "verified",
                "active_llm_model": "openai/gemma4:31b",
                "llm_base_url": "http://host.docker.internal:11434/v1",
                "base_url": "http://127.0.0.1:9000",
                "version": "1.49.5",
                "sdk_version": "1.2.3",
                "tools_version": "1.2.4",
                "workspace_version": "1.2.5",
                "conversation_runtime": "local",
                "build_git_sha": "a" * 40,
                "build_git_ref": "main",
                "llm_api_key_is_set": True,
            },
        }

        canonical = runtime_preflight_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("a" * 40, canonical.revision)
        self.assertEqual(True, canonical.result["openhands_agent_server"]["llm_auth_configured"])
        self.assertNotIn("llm_api_key_is_set", str(canonical.result))
        self.assertNotIn("secret", str(canonical.result).lower())

        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "runtime-preflight.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))

    def test_runtime_preflight_rejects_unavailable_model(self):
        result = {
            "status": "verified",
            "profile_name": "development-local",
            "provider": "ollama",
            "surface": "local",
            "integration": "openhands_llm_ollama",
            "connection_mode": "local",
            "model": "gemma4:31b",
            "ollama_base_url": "http://127.0.0.1:11434",
            "ollama_version": "0.12.0",
            "model_available": False,
        }

        with self.assertRaisesRegex(EvidenceContractError, "exact installed model"):
            runtime_preflight_evidence(
                result,
                observed_at="2026-09-28T18:00:00Z",
            )

    def test_promotion_ready_result_is_verified(self):
        result = PromotionReadiness(
            repository=REPOSITORY,
            source=BranchSnapshot("ai/integration", SOURCE_SHA, True),
            target=BranchSnapshot("develop", TARGET_SHA, True),
            compare=CompareSnapshot("ahead", 2, 0, 2, 2, True),
            validation=ValidationRun(
                id=100,
                workflow=".github/workflows/validate.yml",
                status="completed",
                conclusion="success",
                head_sha=SOURCE_SHA,
                url="https://github.com/example/actions/runs/100",
                evidence_type="branch-push",
                validated_sha=SOURCE_SHA,
            ),
            blockers=(),
        )

        evidence = promotion_readiness_evidence(
            result,
            observed_at=datetime(2026, 9, 28, 18, 0, tzinfo=timezone.utc),
        )

        self.assertEqual("verified", evidence.status)
        self.assertEqual(SOURCE_SHA, evidence.revision)
        self.assertEqual((), evidence.uncertainty)
        self.assertEqual(evidence.evidence_id, evidence.evidence_sha256)

    def test_promotion_fallback_is_explicit_uncertainty(self):
        result = PromotionReadiness(
            repository=REPOSITORY,
            source=BranchSnapshot("ai/integration", SOURCE_SHA, True),
            target=BranchSnapshot("main", TARGET_SHA, True),
            compare=CompareSnapshot("ahead", 2, 0, 2, 2, True),
            validation=ValidationRun(
                id=200,
                workflow=".github/workflows/validate.yml",
                status="completed",
                conclusion="success",
                head_sha="3333333333333333333333333333333333333333",
                url="https://github.com/example/actions/runs/200",
                evidence_type="merged-pull-request",
                validated_sha=SOURCE_SHA,
                pull_request_number=123,
            ),
            blockers=(),
        )

        evidence = promotion_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", evidence.status)
        self.assertEqual(1, len(evidence.uncertainty))
        self.assertIn("merged-pull-request", evidence.uncertainty[0])

    def test_blocked_promotion_is_failed(self):
        result = PromotionReadiness(
            repository=REPOSITORY,
            source=BranchSnapshot("ai/integration", SOURCE_SHA, True),
            target=BranchSnapshot("develop", TARGET_SHA, False),
            compare=CompareSnapshot("behind", 1, 1, 2, 2, True),
            validation=None,
            blockers=("develop must remain protected.",),
        )

        evidence = promotion_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("failed", evidence.status)
        self.assertIn("develop must remain protected.", evidence.result["blockers"])

    def test_promotion_evidence_round_trips(self):
        result = PromotionReadiness(
            repository=REPOSITORY,
            source=BranchSnapshot("ai/integration", SOURCE_SHA, True),
            target=BranchSnapshot("develop", TARGET_SHA, True),
            compare=CompareSnapshot("ahead", 2, 0, 2, 2, True),
            validation=None,
            blockers=("missing validation",),
        )
        evidence = promotion_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "evidence.json"
            from evidence_contract import write_evidence

            write_evidence(evidence, path)
            self.assertEqual(evidence, read_and_validate_evidence(path))

    def test_version_verification_ready_result_is_verified(self):
        evidence = VersionEvidence(
            schema_version=1,
            claims=(
                VersionClaim(
                    component="python",
                    version="3.13",
                    scope="language",
                    source="pyproject.toml",
                    source_sha256="a" * 64,
                ),
            ),
            external_verification_pending=False,
        )

        canonical = version_verification_evidence(
            evidence,
            observed_at="2026-09-28T18:00:00Z",
            revision="7c2d2247abf2d4463a2167d20e7ab18a808a24ee",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual(
            "7c2d2247abf2d4463a2167d20e7ab18a808a24ee",
            canonical.revision,
        )
        self.assertEqual("3.13", canonical.result["claims"][0]["version"])
        self.assertEqual("a" * 64, canonical.result["claims"][0]["source_sha256"])
        self.assertEqual(canonical.evidence_id, canonical.evidence_sha256)

    def test_version_verification_pending_result_remains_pending(self):
        evidence = VersionEvidence(
            schema_version=1,
            claims=(
                VersionClaim(
                    component="python",
                    version="3.13",
                    scope="language",
                    source="pyproject.toml",
                    source_sha256="b" * 64,
                ),
            ),
            external_verification_pending=True,
        )

        canonical = version_verification_evidence(
            evidence,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("pending", canonical.status)
        self.assertIsNone(canonical.revision)
        self.assertEqual(1, len(canonical.uncertainty))
        self.assertIn("pending", canonical.uncertainty[0].lower())

    def test_version_verification_evidence_round_trips(self):
        evidence = VersionEvidence(
            schema_version=1,
            claims=(
                VersionClaim(
                    component="kotlin",
                    version="2.2.20",
                    scope="compiler",
                    source="gradle.properties",
                    source_sha256="c" * 64,
                ),
            ),
            external_verification_pending=False,
        )
        canonical = version_verification_evidence(
            evidence,
            observed_at="2026-09-28T18:00:00Z",
        )

        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "version-evidence.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))




    def test_requirements_clarification_ready_is_verified(self):
        report = RequirementsReport(
            path="/tmp/work-item.md",
            status="ready",
            questions=(
                ClarificationQuestion(
                    "dependencies.unknown",
                    "warning",
                    "Dependencies",
                    "Are there dependencies?",
                    "No dependencies are explicitly recorded.",
                ),
            ),
        )
        canonical = requirements_clarification_evidence(
            report,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("verified", canonical.status)
        self.assertTrue(canonical.result["ready"])
        self.assertEqual("dependencies.unknown", canonical.result["questions"][0]["question_id"])

    def test_requirements_clarification_blocked_is_failed(self):
        report = RequirementsReport(
            path="/tmp/work-item.md",
            status="needs-clarification",
            questions=(
                ClarificationQuestion(
                    "intent.outcome",
                    "blocker",
                    "Intent",
                    "What outcome is required?",
                    "Intent is missing.",
                ),
            ),
        )
        canonical = requirements_clarification_evidence(
            report,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("failed", canonical.status)
        self.assertEqual(1, canonical.result["summary"]["blockers"])

    def test_workflow_composition_is_verified_and_preserves_conditions(self):
        composition = WorkflowComposition(
            work_item_kind="refactoring",
            steps=(
                WorkflowStep("requirements-clarification", "workflow", True),
                WorkflowStep(
                    "architecture-planning",
                    "workflow",
                    False,
                    "Run when architecture-relevant constraints are present.",
                ),
            ),
        )
        canonical = workflow_composition_evidence(
            composition,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("verified", canonical.status)
        self.assertEqual("refactoring", canonical.subject.split(":", 1)[1])
        self.assertFalse(canonical.result["steps"][1]["required"])
        self.assertIn("architecture-relevant", canonical.result["steps"][1]["condition"])

    def test_architecture_planning_ready_preserves_information_classes(self):
        plan = ArchitecturePlan(
            path="/tmp/work-item.md",
            work_item_id="135",
            lifecycle_state="ready",
            status="ready",
            requirements_status="ready",
            evidence=(
                ArchitectureEvidence(
                    "technical-notes.1",
                    "Technical notes",
                    "Affected component: evidence planning.",
                ),
            ),
            deductions=(
                ArchitectureDeduction(
                    "boundaries.explicit-components",
                    "Explicit component reference exists.",
                    "Preserve the named boundary.",
                ),
            ),
            constraints=("Preserve the named boundary.",),
            boundaries=("Add provenance adapter.",),
            affected_components=("evidence planning",),
            adr_needs=(),
            non_goals=("Change execution behavior.",),
            user_owned_decisions=(
                ArchitectureQuestion(
                    "decision.1",
                    "user",
                    "Choose the long-term promotion policy.",
                    "Business decision remains user-owned.",
                ),
            ),
            blockers=(),
        )
        canonical = architecture_planning_evidence(
            plan,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("verified", canonical.status)
        self.assertEqual("work-item:135", canonical.subject)
        self.assertEqual(1, len(canonical.result["evidence"]))
        self.assertEqual(1, len(canonical.result["deductions"]))
        self.assertEqual(1, len(canonical.result["user_owned_decisions"]))

    def test_architecture_planning_blocked_is_failed(self):
        plan = ArchitecturePlan(
            path="/tmp/work-item.md",
            work_item_id="135",
            lifecycle_state="ready",
            status="blocked",
            requirements_status="ready",
            evidence=(),
            deductions=(),
            constraints=(),
            boundaries=(),
            affected_components=(),
            adr_needs=(),
            non_goals=(),
            user_owned_decisions=(),
            blockers=(
                ArchitectureQuestion(
                    "architecture.affected-components",
                    "engineering-evidence",
                    "Which component is affected?",
                    "No explicit component reference was found.",
                ),
            ),
        )
        canonical = architecture_planning_evidence(
            plan,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("failed", canonical.status)
        self.assertEqual(
            "architecture.affected-components",
            canonical.result["blockers"][0]["question_id"],
        )

    def test_planning_evidence_round_trips(self):
        report = RequirementsReport(
            path="/tmp/work-item.md",
            status="ready",
            questions=(),
        )
        canonical = requirements_clarification_evidence(
            report,
            observed_at="2026-09-28T18:00:00Z",
        )
        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "requirements-evidence.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))

    def test_verified_lifecycle_mutation_is_verified(self):
        result = MutationEvidence(
            provider="github-issues",
            operation="transition",
            work_item_id="128",
            state_before="verification",
            state_after="review",
            verified=True,
            reference="https://github.com/KenlikDev/aegis-engineering-os/issues/128",
            identifier=128,
        )

        canonical = mutation_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual("work-item:128", canonical.subject)
        self.assertEqual("verification", canonical.result["state_before"])
        self.assertEqual("review", canonical.result["state_after"])
        self.assertEqual(128, canonical.result["identifier"])
        self.assertEqual(
            ["https://github.com/KenlikDev/aegis-engineering-os/issues/128"],
            list(canonical.references),
        )

    def test_unverified_lifecycle_mutation_is_unknown(self):
        result = MutationEvidence(
            provider="memory",
            operation="transition",
            work_item_id="128",
            state_before="verification",
            state_after="review",
            verified=False,
            reference=None,
            identifier="transition-1",
        )

        canonical = mutation_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("unknown", canonical.status)
        self.assertFalse(canonical.result["verified"])
        self.assertEqual(1, len(canonical.uncertainty))
        self.assertIn("read-after-write", canonical.uncertainty[0])

    def test_lifecycle_mutation_evidence_round_trips(self):
        result = MutationEvidence(
            provider="github-issues",
            operation="comment",
            work_item_id="128",
            verified=True,
            reference="https://github.com/KenlikDev/aegis-engineering-os/issues/128#issuecomment-1",
            identifier=1,
        )
        canonical = mutation_evidence(result, observed_at="2026-09-28T18:00:00Z")

        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "mutation-evidence.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))


    def test_knowledge_gap_candidate_is_pending(self):
        with __import__("tempfile").TemporaryDirectory() as temp:
            record = create_candidate(
                scope="global",
                capability="safe knowledge activation",
                problem="Candidate knowledge needs focused validation.",
                proposed_change="Validate before considering promotion.",
                references=["https://docs.example.test/knowledge"],
                store_root=temp,
                candidate_id="13000000-0000-4000-8000-000000000001",
            )

            canonical = knowledge_gap_evidence(
                record,
                observed_at="2026-09-28T18:00:00Z",
            )

            self.assertEqual("pending", canonical.status)
            self.assertEqual(
                "candidate:13000000-0000-4000-8000-000000000001",
                canonical.subject,
            )
            self.assertEqual(record.candidate.candidate_sha256, canonical.revision)
            self.assertEqual("candidate", canonical.result["state"])
            self.assertEqual(
                record.candidate.candidate_sha256,
                canonical.result["candidate"]["candidate_sha256"],
            )
            self.assertEqual(1, len(canonical.uncertainty))

    def test_knowledge_gap_validated_is_verified(self):
        with __import__("tempfile").TemporaryDirectory() as temp:
            record = create_candidate(
                scope="project",
                capability="verified deployment guidance",
                problem="Deployment rollback guidance is missing.",
                proposed_change="Create project guidance after a focused rollback test.",
                references=["https://docs.example.test/deployment"],
                store_root=temp,
                candidate_id="13000000-0000-4000-8000-000000000002",
            )
            path = __import__("pathlib").Path(temp) / (
                "13000000-0000-4000-8000-000000000002.json"
            )
            record = validate_candidate(
                path,
                scenario="Run one deterministic rollback scenario.",
                evidence_refs=["https://ci.example.test/runs/130"],
            )

            canonical = knowledge_gap_evidence(
                record,
                observed_at="2026-09-28T18:00:00Z",
            )

            self.assertEqual("verified", canonical.status)
            self.assertEqual("validated", canonical.result["state"])
            self.assertEqual(
                "https://ci.example.test/runs/130",
                canonical.result["validation"]["evidence_refs"][0],
            )

    def test_knowledge_gap_rejected_is_failed_and_non_active(self):
        with __import__("tempfile").TemporaryDirectory() as temp:
            record = create_candidate(
                scope="global",
                capability="rejected candidate",
                problem="The observed scenario is too narrow.",
                proposed_change="Do not activate the proposed guidance.",
                references=["https://docs.example.test/rejected"],
                store_root=temp,
                candidate_id="13000000-0000-4000-8000-000000000003",
            )
            path = __import__("pathlib").Path(temp) / (
                "13000000-0000-4000-8000-000000000003.json"
            )
            record = reject_candidate(
                path,
                reason="The scenario does not generalize safely.",
            )

            canonical = knowledge_gap_evidence(
                record,
                observed_at="2026-09-28T18:00:00Z",
            )

            self.assertEqual("failed", canonical.status)
            self.assertEqual("rejected", canonical.result["state"])
            self.assertEqual(1, len(canonical.uncertainty))
            self.assertIn("must not be treated as active", canonical.uncertainty[0])

    def test_knowledge_gap_evidence_round_trips(self):
        with __import__("tempfile").TemporaryDirectory() as temp:
            record = create_candidate(
                scope="global",
                capability="knowledge provenance",
                problem="Candidate evidence must preserve original provenance.",
                proposed_change="Keep the candidate hash and validation state.",
                references=["https://docs.example.test/provenance"],
                store_root=temp,
                candidate_id="13000000-0000-4000-8000-000000000004",
            )
            canonical = knowledge_gap_evidence(
                record,
                observed_at="2026-09-28T18:00:00Z",
            )
            path = __import__("pathlib").Path(temp) / "knowledge-gap-evidence.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))

    def test_openhands_finished_result_is_verified(self):
        result = OpenHandsExecutionResult(
            conversation_id="12345178-1234-5178-1234-517812345178",
            execution_status="finished",
            outcome="finished",
            state={"execution_status": "finished", "api_key": "[REDACTED]"},
            events=(
                {"kind": "message", "content": "completed"},
            ),
        )

        canonical = openhands_execution_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual(
            "conversation:12345178-1234-5178-1234-517812345178",
            canonical.subject,
        )
        self.assertEqual(
            {"execution_status": "finished"},
            canonical.result["state"],
        )
        self.assertEqual(1, canonical.result["event_count"])

    def test_openhands_failed_result_is_failed_with_uncertainty(self):
        result = OpenHandsExecutionResult(
            conversation_id="22345178-1234-5178-1234-517812345178",
            execution_status="error",
            outcome="error",
            state={"execution_status": "error"},
            events=(),
        )

        canonical = openhands_execution_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("failed", canonical.status)
        self.assertEqual(1, len(canonical.uncertainty))
        self.assertIn("error", canonical.uncertainty[0])

    def test_openhands_stuck_result_is_failed(self):
        result = OpenHandsExecutionResult(
            conversation_id="32345178-1234-5178-1234-517812345178",
            execution_status="stuck",
            outcome="stuck",
            state={"execution_status": "stuck"},
            events=(),
        )

        canonical = openhands_execution_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("failed", canonical.status)
        self.assertEqual("stuck", canonical.result["outcome"])

    def test_openhands_blocked_result_is_failed(self):
        result = OpenHandsExecutionResult(
            conversation_id="42345178-1234-5178-1234-517812345178",
            execution_status="waiting_for_confirmation",
            outcome="blocked",
            state={"execution_status": "waiting_for_confirmation"},
            events=(),
        )

        canonical = openhands_execution_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("failed", canonical.status)
        self.assertEqual("blocked", canonical.result["outcome"])

    def test_ci_diagnosis_healthy_result_is_verified(self):
        run = WorkflowRunSnapshot(
            repository=REPOSITORY,
            run_id=101,
            name="Aegis Validation",
            workflow_path=".github/workflows/validate.yml",
            event="push",
            status="completed",
            conclusion="success",
            head_branch="ai/integration",
            head_sha="3" * 40,
            url="https://github.com/example/actions/runs/101",
        )
        report = DiagnosticReport(
            run=run,
            jobs=(
                JobSnapshot(
                    job_id=11,
                    name="Validate Aegis",
                    status="completed",
                    conclusion="success",
                    url="https://github.com/example/jobs/11",
                ),
            ),
            findings=(),
            status="healthy",
        )

        canonical = ci_diagnosis_evidence(
            report,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual("workflow-run:101", canonical.subject)
        self.assertEqual("3" * 40, canonical.revision)
        self.assertEqual([], canonical.result["findings"])

    def test_ci_diagnosis_diagnosed_result_is_failed(self):
        run = WorkflowRunSnapshot(
            repository=REPOSITORY,
            run_id=102,
            name="Aegis Validation",
            workflow_path=".github/workflows/validate.yml",
            event="pull_request",
            status="completed",
            conclusion="failure",
            head_branch="ai/feature/test",
            head_sha="4" * 40,
            url="https://github.com/example/actions/runs/102",
        )
        finding = DiagnosticFinding(
            category="test-failure",
            severity="medium",
            actionable=True,
            job_id=12,
            job="Validate Aegis",
            step="Run policy tests",
            message="The observed CI output indicates a test failure.",
            evidence="FAILED (failures=1)",
        )
        report = DiagnosticReport(
            run=run,
            jobs=(
                JobSnapshot(
                    job_id=12,
                    name="Validate Aegis",
                    status="completed",
                    conclusion="failure",
                    url="https://github.com/example/jobs/12",
                    failed_steps=("Run policy tests",),
                ),
            ),
            findings=(finding,),
            status="diagnosed",
        )

        canonical = ci_diagnosis_evidence(
            report,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("failed", canonical.status)
        self.assertEqual("test-failure", canonical.result["findings"][0]["category"])
        self.assertEqual("medium", canonical.result["findings"][0]["severity"])
        self.assertEqual("FAILED (failures=1)", canonical.result["findings"][0]["evidence"])

    def test_ci_diagnosis_inconclusive_result_is_unknown(self):
        run = WorkflowRunSnapshot(
            repository=REPOSITORY,
            run_id=103,
            name="Aegis Validation",
            workflow_path=".github/workflows/validate.yml",
            event="pull_request",
            status="completed",
            conclusion="failure",
            head_branch="ai/feature/test",
            head_sha="5" * 40,
            url="https://github.com/example/actions/runs/103",
        )
        finding = DiagnosticFinding(
            category="unknown",
            severity="low",
            actionable=False,
            job_id=13,
            job="Unknown",
            step=None,
            message="No supported deterministic failure signature was found in the observed evidence.",
            evidence="unexpected failure",
        )
        report = DiagnosticReport(
            run=run,
            jobs=(
                JobSnapshot(
                    job_id=13,
                    name="Unknown",
                    status="completed",
                    conclusion="failure",
                    url="https://github.com/example/jobs/13",
                ),
            ),
            findings=(finding,),
            status="inconclusive",
        )

        canonical = ci_diagnosis_evidence(
            report,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("unknown", canonical.status)
        self.assertEqual(1, len(canonical.uncertainty))
        self.assertIn("deterministic failure signature", canonical.uncertainty[0])

    def test_ci_diagnosis_evidence_round_trips(self):
        run = WorkflowRunSnapshot(
            repository=REPOSITORY,
            run_id=104,
            name="Aegis Validation",
            workflow_path=".github/workflows/validate.yml",
            event="pull_request",
            status="completed",
            conclusion="failure",
            head_branch="ai/feature/test",
            head_sha="6" * 40,
            url="https://github.com/example/actions/runs/104",
        )
        report = DiagnosticReport(
            run=run,
            jobs=(),
            findings=(),
            status="inconclusive",
        )
        canonical = ci_diagnosis_evidence(
            report,
            observed_at="2026-09-28T18:00:00Z",
        )

        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "ci-diagnosis.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))

    def test_integration_merge_verified_result_preserves_exact_identity(self):
        result = {
            "status": "verified",
            "work_item_id": "143",
            "validation_head_sha": SOURCE_SHA,
            "pull_request": {
                "number": 143,
                "url": "https://github.com/example/pull/143",
                "head": "ai/feature/143-integration-merge-provenance",
                "head_sha": SOURCE_SHA,
                "base": "ai/integration",
                "state": "closed",
                "merged": True,
                "merge_commit_sha": TARGET_SHA,
            },
            "integration": {
                "branch": "ai/integration",
                "sha": TARGET_SHA,
                "protected": True,
            },
            "traceability_verified": True,
            "work_item": {
                "state_after": "integration",
                "transition_verified": True,
            },
        }

        canonical = integration_merge_evidence(
            result,
            repository=REPOSITORY,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual("integration-merge", canonical.kind)
        self.assertEqual("work-item:143", canonical.subject)
        self.assertEqual(TARGET_SHA, canonical.revision)
        self.assertEqual(SOURCE_SHA, canonical.result["validation_head_sha"])
        self.assertEqual(TARGET_SHA, canonical.result["integration"]["sha"])
        self.assertTrue(canonical.result["work_item"]["transition_verified"])
        self.assertEqual(canonical.evidence_id, canonical.evidence_sha256)

        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "integration-merge-evidence.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))

    def test_integration_merge_not_merged_remains_unknown(self):
        result = {
            "status": "not-merged",
            "work_item_id": "143",
            "pull_request": {
                "number": 143,
                "url": "https://github.com/example/pull/143",
                "state": "closed",
                "merged": False,
            },
            "integration": {
                "branch": "ai/integration",
                "sha": SOURCE_SHA,
                "protected": True,
            },
            "work_item": {
                "state_after": "review",
                "transition_verified": False,
            },
        }

        canonical = integration_merge_evidence(
            result,
            repository=REPOSITORY,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("unknown", canonical.status)
        self.assertIsNone(canonical.revision)
        self.assertEqual(1, len(canonical.uncertainty))
        self.assertIn("not merged", canonical.uncertainty[0])

    def test_implementation_readiness_verified_result_is_verified(self):
        result = ImplementationReadiness(
            work_item_path="/tmp/work-item.md",
            work_item_id="118",
            work_item_kind="feature",
            lifecycle_state="ready",
            requirements_status="ready",
            architecture_required=False,
            version_evidence_ref=".aegis/version-evidence.json",
            version_external_verification_pending=False,
            observations=(
                ReadinessObservation(
                    "requirements",
                    "passed",
                    "Requirements clarification has no blocker-level questions.",
                ),
                ReadinessObservation(
                    "architecture",
                    "not-required",
                    "Architecture impact was explicitly classified as not required for this work item.",
                ),
            ),
            blockers=(),
            composition_steps=("feature-implementation", "testing"),
        )

        canonical = implementation_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual("work-item:118", canonical.subject)
        self.assertEqual("feature", canonical.result["work_item_kind"])
        self.assertEqual(
            ["feature-implementation", "testing"],
            canonical.result["composition_steps"],
        )
        self.assertEqual(canonical.evidence_id, canonical.evidence_sha256)

    def test_implementation_readiness_evidence_set_is_preserved(self):
        result = ImplementationReadiness(
            work_item_path="/tmp/work-item.md",
            work_item_id="138",
            work_item_kind="feature",
            lifecycle_state="ready",
            requirements_status="ready",
            architecture_required=False,
            version_evidence_ref=".aegis/version-evidence.json",
            version_external_verification_pending=False,
            observations=(),
            blockers=(),
            composition_steps=("feature-implementation",),
            evidence_set=EvidenceSetReadiness(
                status="verified",
                bundle_id="a" * 64,
                requirements_ref=".aegis/readiness-requirements.json",
                requirements_satisfied=2,
                requirements_total=2,
                detail="Explicit evidence-set requirements are satisfied.",
            ),
        )

        canonical = implementation_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("verified", canonical.result["evidence_set"]["status"])
        self.assertEqual("a" * 64, canonical.result["evidence_set"]["bundle_id"])
        self.assertEqual(2, canonical.result["evidence_set"]["requirements_satisfied"])
        self.assertEqual(2, canonical.result["evidence_set"]["requirements_total"])

    def test_implementation_readiness_pending_version_remains_pending(self):
        result = ImplementationReadiness(
            work_item_path="/tmp/work-item.md",
            work_item_id="118",
            work_item_kind="feature",
            lifecycle_state=None,
            requirements_status="ready",
            architecture_required=False,
            version_evidence_ref=".aegis/version-evidence.json",
            version_external_verification_pending=True,
            observations=(
                ReadinessObservation(
                    "version-verification",
                    "pending",
                    "External compatibility verification remains pending.",
                ),
            ),
            blockers=(),
            composition_steps=("feature-implementation",),
        )

        canonical = implementation_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("pending", canonical.status)
        self.assertEqual(1, len(canonical.uncertainty))
        self.assertIn("pending", canonical.uncertainty[0].lower())

    def test_implementation_readiness_blocked_result_is_failed(self):
        result = ImplementationReadiness(
            work_item_path="/tmp/work-item.md",
            work_item_id="118",
            work_item_kind="feature",
            lifecycle_state=None,
            requirements_status="blocked",
            architecture_required=True,
            version_evidence_ref=".aegis/version-evidence.json",
            version_external_verification_pending=False,
            observations=(
                ReadinessObservation(
                    "requirements",
                    "blocked",
                    "2 clarification question(s) remain.",
                ),
            ),
            blockers=("Requirements clarification still contains blocker-level questions.",),
            composition_steps=("feature-implementation", "testing"),
        )

        canonical = implementation_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("failed", canonical.status)
        self.assertEqual(
            ["Requirements clarification still contains blocker-level questions."],
            canonical.result["blockers"],
        )


    def test_testing_verified_result_is_preserved(self):
        result = {
            "status": "verified",
            "project": "/tmp/project",
            "manifest": "/tmp/project/.aegis/quality-gates.json",
            "required_failures": [],
            "gates": [
                {
                    "id": "unit-tests",
                    "required": True,
                    "status": "passed",
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_seconds": 1.234,
                    "stdout": "passed\\n",
                    "stderr": "",
                }
            ],
            "work_item": None,
            "testing_contract": {
                "required_gate_ids": ["unit-tests"],
                "gate_count": 1,
            },
        }

        canonical = testing_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
            revision="d932c1f343cb38ceb6d6a28d4ef753d01a9f6e43",
        )

        self.assertEqual("verified", canonical.status)
        self.assertEqual(
            "d932c1f343cb38ceb6d6a28d4ef753d01a9f6e43",
            canonical.revision,
        )
        self.assertEqual(["unit-tests"], canonical.result["testing_contract"]["required_gate_ids"])
        self.assertEqual("passed", canonical.result["gates"][0]["status"])

    def test_testing_failed_result_is_preserved(self):
        result = {
            "status": "failed",
            "project": "/tmp/project",
            "manifest": "/tmp/project/.aegis/quality-gates.json",
            "required_failures": ["unit-tests"],
            "gates": [
                {
                    "id": "unit-tests",
                    "required": True,
                    "status": "failed",
                    "exit_code": 1,
                    "timed_out": False,
                    "duration_seconds": 0.1,
                    "stdout": "",
                    "stderr": "failed",
                }
            ],
            "work_item": None,
            "testing_contract": {
                "required_gate_ids": ["unit-tests"],
                "gate_count": 1,
            },
        }

        canonical = testing_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )

        self.assertEqual("failed", canonical.status)
        self.assertEqual(["unit-tests"], canonical.result["required_failures"])

    def test_testing_evidence_round_trips(self):
        result = {
            "status": "verified",
            "project": "/tmp/project",
            "manifest": "/tmp/project/.aegis/quality-gates.json",
            "required_failures": [],
            "gates": [],
            "work_item": None,
            "testing_contract": {
                "required_gate_ids": [],
                "gate_count": 0,
            },
        }
        canonical = testing_evidence(result, observed_at="2026-09-28T18:00:00Z")

        with __import__("tempfile").TemporaryDirectory() as temp:
            path = __import__("pathlib").Path(temp) / "testing-evidence.json"
            write_evidence(canonical, path)
            self.assertEqual(canonical, read_and_validate_evidence(path))


    def test_security_review_without_high_findings_is_verified(self):
        result = SecurityReviewResult(
            root="/tmp/project",
            status="ready",
            findings=(
                SecurityFinding(
                    rule_id="workflow.permissions-write",
                    severity="medium",
                    path=".github/workflows/example.yml",
                    message="Verify that the write permission is strictly required.",
                    line=12,
                ),
            ),
        )
        canonical = security_review_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
            revision="3872d1e1e6766acf0e6efa9031c6c94edb49571b",
        )
        self.assertEqual("verified", canonical.status)
        self.assertEqual("repository-security", canonical.subject)
        self.assertEqual("medium", canonical.result["findings"][0]["severity"])
        self.assertEqual(
            "3872d1e1e6766acf0e6efa9031c6c94edb49571b",
            canonical.revision,
        )

    def test_security_review_high_finding_is_failed(self):
        result = SecurityReviewResult(
            root="/tmp/project",
            status="blocked",
            findings=(
                SecurityFinding(
                    rule_id="secrets.high-confidence",
                    severity="high",
                    path="tools/example.py",
                    message="High-confidence credential material appears in a reviewed source/config file.",
                    line=4,
                ),
            ),
        )
        canonical = security_review_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("failed", canonical.status)
        self.assertEqual(1, canonical.result["summary"]["high"])


    def test_release_ready_result_is_verified(self):
        result = ReleaseReadiness(
            repository=REPOSITORY,
            target=BranchSnapshot("main", TARGET_SHA, True),
            validation=None,
            version="0.1.0-alpha.1",
            manifest_version="0.1.0-alpha.1",
            registry_version="0.1.0-alpha.1",
            version_valid=True,
            changelog=ChangelogSnapshot(True, True, True, False),
            blockers=(),
        )
        evidence = release_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("verified", evidence.status)
        self.assertEqual(TARGET_SHA, evidence.revision)

    def test_release_blocked_result_is_failed(self):
        result = ReleaseReadiness(
            repository=REPOSITORY,
            target=BranchSnapshot("main", TARGET_SHA, True),
            validation=None,
            version="0.1.0-alpha.1",
            manifest_version="9.9.9",
            registry_version="0.1.0-alpha.1",
            version_valid=True,
            changelog=ChangelogSnapshot(True, True, True, True),
            blockers=("VERSION and aegis-manifest.json disagree.",),
        )
        evidence = release_readiness_evidence(
            result,
            observed_at="2026-09-28T18:00:00Z",
        )
        self.assertEqual("failed", evidence.status)
        self.assertIn(
            "VERSION and aegis-manifest.json disagree.",
            evidence.result["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
