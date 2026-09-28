import sys
import unittest
from datetime import datetime, timezone

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_adapters import (  # noqa: E402
    promotion_readiness_evidence,
    implementation_readiness_evidence,
    release_readiness_evidence,
    testing_evidence,
    version_verification_evidence,
)
from evidence_contract import (  # noqa: E402
    read_and_validate_evidence,
    write_evidence,
)
from promotion_readiness import BranchSnapshot, CompareSnapshot, PromotionReadiness, ValidationRun  # noqa: E402
from implementation_readiness import (  # noqa: E402
    ImplementationReadiness,
    ReadinessObservation,
)
from release_readiness import ChangelogSnapshot, ReleaseReadiness  # noqa: E402
from version_verification import VersionClaim, VersionEvidence  # noqa: E402



REPOSITORY = "KenlikDev/aegis-engineering-os"
SOURCE_SHA = "1111111111111111111111111111111111111111"
TARGET_SHA = "2222222222222222222222222222222222222222"


class EvidenceAdapterTests(unittest.TestCase):
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
