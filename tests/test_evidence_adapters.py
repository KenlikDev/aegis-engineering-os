import sys
import unittest
from datetime import datetime, timezone

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_adapters import (  # noqa: E402
    promotion_readiness_evidence,
    release_readiness_evidence,
    version_verification_evidence,
)
from evidence_contract import (  # noqa: E402
    read_and_validate_evidence,
    write_evidence,
)
from promotion_readiness import BranchSnapshot, CompareSnapshot, PromotionReadiness, ValidationRun  # noqa: E402
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
