import sys
import unittest
from urllib.parse import parse_qs, urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from promotion_readiness import (  # noqa: E402
    DEFAULT_SOURCE_BRANCH,
    GitHubPromotionProvider,
    PromotionReadinessError,
)


REPOSITORY = "KenlikDev/aegis-engineering-os"
SOURCE_SHA = "1111111111111111111111111111111111111111"
TARGET_SHA = "2222222222222222222222222222222222222222"


class FakeTransport:
    def __init__(
        self,
        *,
        target_behind: int = 0,
        compare_status: str | None = None,
        changed_files: int = 2,
        validation_conclusion: str | None = "success",
        validation_sha: str = SOURCE_SHA,
        source_protected: bool = True,
        target_protected: bool = True,
        merged_pr_validation: bool = False,
        merged_pr_base: str = DEFAULT_SOURCE_BRANCH,
        merged_pr_merged: bool = True,
        merged_pr_merge_sha: str = SOURCE_SHA,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.target_behind = target_behind
        self.compare_status = compare_status or ("ahead" if target_behind == 0 else "behind")
        self.changed_files = changed_files
        self.validation_conclusion = validation_conclusion
        self.validation_sha = validation_sha
        self.source_protected = source_protected
        self.target_protected = target_protected
        self.merged_pr_validation = merged_pr_validation
        self.merged_pr_base = merged_pr_base
        self.merged_pr_merged = merged_pr_merged
        self.merged_pr_merge_sha = merged_pr_merge_sha

    def __call__(self, method, url, headers, payload):  # noqa: ANN001
        path = url.removeprefix("https://api.github.com")
        self.calls.append((method, path))

        if path == f"/repos/{REPOSITORY}/branches/{DEFAULT_SOURCE_BRANCH.replace('/', '%2F')}":
            return 200, {
                "name": DEFAULT_SOURCE_BRANCH,
                "protected": self.source_protected,
                "commit": {"sha": SOURCE_SHA},
            }

        if path == f"/repos/{REPOSITORY}/branches/develop":
            return 200, {
                "name": "develop",
                "protected": self.target_protected,
                "commit": {"sha": TARGET_SHA},
            }

        if path == f"/repos/{REPOSITORY}/compare/{TARGET_SHA}...{SOURCE_SHA}":
            return 200, {
                "status": self.compare_status,
                "ahead_by": 2 if self.compare_status in {"ahead", "diverged"} else 0,
                "behind_by": self.target_behind,
                "total_commits": 2,
                "files": [
                    {"filename": f"file-{index}.txt"}
                    for index in range(self.changed_files)
                ],
            }

        workflow_path_prefix = (
            f"/repos/{REPOSITORY}/actions/workflows/"
            ".github%2Fworkflows%2Fvalidate.yml/runs?"
        )
        if path.startswith(workflow_path_prefix):
            query = parse_qs(urlparse(path).query)
            if "head_sha" in query:
                if self.validation_conclusion is None:
                    return 200, {"workflow_runs": []}
                return 200, {
                    "workflow_runs": [
                        {
                            "id": 100,
                            "name": "Aegis Validation",
                            "status": "completed",
                            "conclusion": self.validation_conclusion,
                            "head_sha": self.validation_sha,
                            "html_url": "https://github.com/KenlikDev/aegis-engineering-os/actions/runs/100",
                        }
                    ]
                }

            if not self.merged_pr_validation:
                return 200, {"workflow_runs": []}

            return 200, {
                "workflow_runs": [
                    {
                        "id": 200,
                        "name": "Aegis Validation",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "4444444444444444444444444444444444444444",
                        "head_branch": "ai/test/84-runtime-tool-inventory",
                        "event": "pull_request",
                        "path": ".github/workflows/validate.yml",
                        "html_url": "https://github.com/KenlikDev/aegis-engineering-os/actions/runs/200",
                    }
                ]
            }

        if path.startswith(f"/repos/{REPOSITORY}/pulls?"):
            query = parse_qs(urlparse(path).query)
            self.calls.append(("GET", path))
            if query.get("state") != ["closed"]:
                return 200, []
            return 200, [
                {
                    "number": 123,
                    "base": {"ref": "ai/integration"},
                    "head": {"ref": "ai/test/84-runtime-tool-inventory"},
                }
            ]

        if path == f"/repos/{REPOSITORY}/pulls/123":
            if not self.merged_pr_validation:
                raise AssertionError("Unexpected merged PR lookup.")
            return 200, {
                "number": 123,
                "state": "closed" if self.merged_pr_merged else "open",
                "merged_at": "2026-09-28T14:00:00Z" if self.merged_pr_merged else None,
                "merge_commit_sha": self.merged_pr_merge_sha if self.merged_pr_merged else None,
                "base": {"ref": self.merged_pr_base},
                "head": {
                    "ref": "ai/test/84-runtime-tool-inventory",
                    "sha": "4444444444444444444444444444444444444444",
                },
            }

        raise AssertionError(f"Unexpected request: {method} {path}")


class PromotionReadinessTests(unittest.TestCase):
    def _provider(self, **kwargs) -> GitHubPromotionProvider:  # noqa: ANN003
        return GitHubPromotionProvider(
            REPOSITORY,
            "secret-token",
            transport=FakeTransport(**kwargs),
        )

    def test_green_exact_source_sha_is_ready(self) -> None:
        result = self._provider().assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertTrue(result.ready)
        self.assertEqual(SOURCE_SHA, result.source.sha)
        self.assertEqual(TARGET_SHA, result.target.sha)
        self.assertEqual(2, result.compare.ahead_by)
        self.assertEqual(0, result.compare.behind_by)
        self.assertEqual(2, result.compare.changed_files_reported)
        self.assertTrue(result.compare.changed_files_complete)
        self.assertIsNotNone(result.validation)
        self.assertEqual(SOURCE_SHA, result.validation.head_sha)
        self.assertEqual(SOURCE_SHA, result.validation.validated_sha)
        self.assertEqual("branch-push", result.validation.evidence_type)
        self.assertIsNone(result.validation.pull_request_number)
        self.assertEqual((), result.blockers)

    def test_stale_expected_source_sha_blocks(self) -> None:
        result = self._provider().assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
            expected_source_sha="3333333333333333333333333333333333333333",
        )
        self.assertFalse(result.ready)
        self.assertIn(
            "ai/integration changed since the promotion snapshot.",
            result.blockers,
        )

    def test_stale_expected_target_sha_blocks(self) -> None:
        result = self._provider().assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
            expected_target_sha="3333333333333333333333333333333333333333",
        )
        self.assertFalse(result.ready)
        self.assertIn(
            "develop changed since the promotion snapshot.",
            result.blockers,
        )

    def test_diverged_history_after_squash_promotion_is_allowed(self) -> None:
        result = self._provider(
            target_behind=5,
            compare_status="diverged",
        ).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertTrue(result.ready)
        self.assertEqual("diverged", result.compare.status)
        self.assertEqual(5, result.compare.behind_by)
        self.assertGreater(result.compare.ahead_by, 0)
        self.assertEqual((), result.blockers)

    def test_history_only_divergence_without_file_delta_blocks(self) -> None:
        result = self._provider(
            target_behind=5,
            compare_status="diverged",
            changed_files=0,
        ).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )

        self.assertFalse(result.ready)
        self.assertIn(
            "Promotion contains history-only divergence with no changed files.",
            result.blockers,
        )
    def test_source_behind_target_blocks(self) -> None:
        result = self._provider(target_behind=1).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertFalse(result.ready)
        self.assertIn(
            "ai/integration is behind develop by 1 commit(s).",
            result.blockers,
        )

    def test_failed_validation_blocks(self) -> None:
        result = self._provider(validation_conclusion="failure").assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertFalse(result.ready)
        self.assertIn(
            "No successful Aegis Validation run exists for the exact ai/integration SHA.",
            result.blockers,
        )

    def test_validation_on_different_sha_blocks(self) -> None:
        result = self._provider(
            validation_conclusion="success",
            validation_sha=TARGET_SHA,
        ).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertFalse(result.ready)

    def test_missing_validation_blocks(self) -> None:
        result = self._provider(validation_conclusion=None).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertFalse(result.ready)

    def test_unprotected_source_blocks(self) -> None:
        result = self._provider(source_protected=False).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertFalse(result.ready)
        self.assertIn("ai/integration must remain protected.", result.blockers)

    def test_unprotected_target_blocks(self) -> None:
        result = self._provider(target_protected=False).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )
        self.assertFalse(result.ready)
        self.assertIn("develop must remain protected.", result.blockers)

    def test_merged_pull_request_validation_is_accepted_as_fallback(self) -> None:
        provider = self._provider(
            validation_conclusion=None,
            merged_pr_validation=True,
        )
        result = provider.assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )

        self.assertTrue(result.ready)
        self.assertIsNotNone(result.validation)
        self.assertEqual("merged-pull-request", result.validation.evidence_type)
        self.assertEqual(SOURCE_SHA, result.validation.validated_sha)
        self.assertEqual(123, result.validation.pull_request_number)
        self.assertNotEqual(SOURCE_SHA, result.validation.head_sha)

    def test_merged_pull_request_wrong_base_is_rejected(self) -> None:
        result = self._provider(
            validation_conclusion=None,
            merged_pr_validation=True,
            merged_pr_base="develop",
        ).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )

        self.assertFalse(result.ready)
        self.assertIsNone(result.validation)

    def test_unmerged_pull_request_is_rejected(self) -> None:
        result = self._provider(
            validation_conclusion=None,
            merged_pr_validation=True,
            merged_pr_merged=False,
        ).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )

        self.assertFalse(result.ready)
        self.assertIsNone(result.validation)

    def test_stale_merged_pull_request_is_rejected(self) -> None:
        result = self._provider(
            validation_conclusion=None,
            merged_pr_validation=True,
            merged_pr_merge_sha=TARGET_SHA,
        ).assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )

        self.assertFalse(result.ready)
        self.assertIsNone(result.validation)

    def test_push_validation_remains_preferred_over_merged_pr_fallback(self) -> None:
        provider = self._provider(
            validation_conclusion="success",
            validation_sha=SOURCE_SHA,
            merged_pr_validation=True,
        )
        result = provider.assess(
            source_branch="ai/integration",
            target_branch="develop",
            workflow=".github/workflows/validate.yml",
        )

        self.assertTrue(result.ready)
        self.assertEqual("branch-push", result.validation.evidence_type)
        self.assertIsNone(result.validation.pull_request_number)

    def test_wrong_source_branch_is_rejected(self) -> None:
        with self.assertRaises(PromotionReadinessError):
            self._provider().assess(
                source_branch="ai/other",
                target_branch="develop",
                workflow=".github/workflows/validate.yml",
            )

    def test_wrong_target_branch_is_rejected(self) -> None:
        with self.assertRaises(PromotionReadinessError):
            self._provider().assess(
                source_branch="ai/integration",
                target_branch="release",
                workflow=".github/workflows/validate.yml",
            )

    def test_malformed_expected_sha_is_rejected(self) -> None:
        with self.assertRaises(PromotionReadinessError):
            self._provider().assess(
                source_branch="ai/integration",
                target_branch="develop",
                workflow=".github/workflows/validate.yml",
                expected_source_sha="not-a-sha",
            )


if __name__ == "__main__":
    unittest.main()
