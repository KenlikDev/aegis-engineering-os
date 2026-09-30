import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import integration_merge as integration_merge_module  # noqa: E402
from integration_merge import (
    GitHubIntegrationMergeProvider,
    IntegrationMergeError,
    IntegrationPullRequest,
    MergeResult,
    sync_integration_merge,
)
from promotion_readiness import BranchSnapshot  # noqa: E402
from work_item_lifecycle import (  # noqa: E402
    InMemoryWorkItemProvider,
    LifecycleState,
    MutationEvidence,
    Traceability,
    WorkItem,
)
from evidence_contract import read_and_validate_evidence  # noqa: E402

REPOSITORY = "KenlikDev/aegis-engineering-os"
PR_NUMBER = 75
HEAD_SHA = "1111111111111111111111111111111111111111"
INTEGRATION_SHA = "2222222222222222222222222222222222222222"
MERGE_SHA = "3333333333333333333333333333333333333333"
ADVANCED_SHA = "4444444444444444444444444444444444444444"


def work_items(state=LifecycleState.REVIEW):
    return InMemoryWorkItemProvider(
        {
            "75": WorkItem(
                id="75",
                title="integration merge",
                state=state,
                provider="memory",
            )
        }
    )


class FakeIntegrationProvider:
    def __init__(
        self,
        *,
        pr_state="open",
        merged=False,
        draft=False,
        mergeable_state="clean",
        protected=True,
        exact_merge=True,
        post_merge_sha=MERGE_SHA,
        base="ai/integration",
        head="ai/feature/75-integration-merge",
        merge_commit_sha=None,
        head_sha=HEAD_SHA,
    ):
        self.repository = REPOSITORY
        self.pr = IntegrationPullRequest(
            number=PR_NUMBER,
            url="https://github.com/KenlikDev/aegis-engineering-os/pull/75",
            head=head,
            head_sha=head_sha,
            base=base,
            state=pr_state,
            merged=merged,
            draft=draft,
            mergeable_state=mergeable_state,
            merge_commit_sha=merge_commit_sha,
            head_repository=REPOSITORY,
            base_repository=REPOSITORY,
        )
        self.integration = BranchSnapshot(
            branch="ai/integration",
            sha=INTEGRATION_SHA,
            protected=protected,
        )
        self.exact_merge = exact_merge
        self.post_merge_sha = post_merge_sha
        self.merge_calls = []

    def get_pull_request(self, number):
        if number != PR_NUMBER:
            raise AssertionError(f"Unexpected pull request number: {number}")
        return self.pr

    def get_branch(self, branch):
        if branch != "ai/integration":
            raise AssertionError(f"Unexpected branch: {branch}")
        if self.pr.merged:
            return BranchSnapshot(
                branch=self.integration.branch,
                sha=self.post_merge_sha,
                protected=self.integration.protected,
            )
        return self.integration

    def target_matches_commit(self, target_branch, commit_sha):
        self.merge_calls.append(("exact", target_branch, commit_sha))
        return self.exact_merge

    def merge_pull_request(self, number, expected_head_sha):
        self.merge_calls.append(("merge", number, expected_head_sha))
        if number != PR_NUMBER or expected_head_sha != HEAD_SHA:
            raise AssertionError("Unexpected merge precondition.")
        self.pr = IntegrationPullRequest(
            number=self.pr.number,
            url=self.pr.url,
            head=self.pr.head,
            head_sha=self.pr.head_sha,
            base=self.pr.base,
            state="closed",
            merged=True,
            draft=False,
            mergeable_state="unknown",
            merge_commit_sha=MERGE_SHA,
            head_repository=REPOSITORY,
            base_repository=REPOSITORY,
        )
        return MergeResult(merged=True, merge_commit_sha=MERGE_SHA)


class UnverifiedTraceabilityProvider(InMemoryWorkItemProvider):
    def attach_traceability(self, work_item_id, traceability):
        return MutationEvidence(
            provider="memory",
            operation="comment",
            work_item_id=work_item_id,
            verified=False,
        )


class UnverifiedTransitionProvider(InMemoryWorkItemProvider):
    def transition(
        self,
        work_item_id,
        target,
        *,
        expected_state=None,
    ):
        current = self.get(work_item_id)
        return MutationEvidence(
            provider=current.provider,
            operation="transition",
            work_item_id=work_item_id,
            state_before=current.state.value,
            state_after=target.value,
            verified=False,
            reference=current.provider_url,
        )


class FakeGitHubTransport:
    def __init__(self, *, head_repository=REPOSITORY, base_repository=REPOSITORY):
        self.calls = []
        self.pr_reads = 0
        self.merge_payload = None
        self.comparison = {"status": "identical", "ahead_by": 0, "behind_by": 0}
        self.head_repository = head_repository
        self.base_repository = base_repository

    def __call__(self, method, url, headers, payload):
        path = url.removeprefix("https://api.github.com")
        self.calls.append((method, path, payload))

        if path == f"/repos/{REPOSITORY}/branches/ai%2Fintegration":
            return 200, {
                "name": "ai/integration",
                "protected": True,
                "commit": {"sha": INTEGRATION_SHA},
            }

        if path == f"/repos/{REPOSITORY}/pulls/{PR_NUMBER}" and method == "GET":
            self.pr_reads += 1
            merged = self.pr_reads >= 2
            return 200, {
                "number": PR_NUMBER,
                "title": "integration merge",
                "body": "",
                "head": {
                    "ref": "ai/feature/75-integration-merge",
                    "sha": HEAD_SHA,
                    "repo": {"full_name": self.head_repository},
                },
                "base": {
                    "ref": "ai/integration",
                    "sha": INTEGRATION_SHA,
                    "repo": {"full_name": self.base_repository},
                },
                "state": "closed" if merged else "open",
                "merged_at": "2026-09-28T15:00:00Z" if merged else None,
                "merge_commit_sha": MERGE_SHA if merged else None,
                "draft": False,
                "mergeable_state": "clean" if not merged else "unknown",
                "html_url": f"https://github.com/KenlikDev/aegis-engineering-os/pull/{PR_NUMBER}",
            }

        if path == f"/repos/{REPOSITORY}/pulls/{PR_NUMBER}/merge" and method == "PUT":
            self.merge_payload = payload
            return 200, {"merged": True, "sha": MERGE_SHA}

        if path == f"/repos/{REPOSITORY}/compare/ai%2Fintegration...{MERGE_SHA}":
            return 200, dict(self.comparison)

        raise AssertionError(f"Unexpected GitHub request: {method} {path}")


class IntegrationMergeTests(unittest.TestCase):
    def test_rejects_fork_origin_before_merge(self):
        provider = FakeIntegrationProvider()
        provider.pr = IntegrationPullRequest(
            number=provider.pr.number,
            url=provider.pr.url,
            head=provider.pr.head,
            head_sha=provider.pr.head_sha,
            base=provider.pr.base,
            state=provider.pr.state,
            merged=False,
            draft=False,
            mergeable_state="clean",
            merge_commit_sha=None,
            head_repository="attacker/example-fork",
            base_repository=REPOSITORY,
        )

        with self.assertRaisesRegex(
            IntegrationMergeError,
            "head and base repositories must match",
        ):
            sync_integration_merge(
                provider,
                work_items(),
                "75",
                PR_NUMBER,
                expected_head_sha=HEAD_SHA,
            )

    def test_successful_merge_advances_review_to_integration(self):
        provider = FakeIntegrationProvider()
        items = work_items()

        result = sync_integration_merge(
            provider,
            items,
            "75",
            PR_NUMBER,
            expected_head_sha=HEAD_SHA,
        )

        self.assertEqual("verified", result["status"])
        self.assertEqual(LifecycleState.INTEGRATION, items.get("75").state)
        self.assertEqual(
            [("merge", PR_NUMBER, HEAD_SHA), ("exact", "ai/integration", MERGE_SHA)],
            provider.merge_calls,
        )
        self.assertIn(MERGE_SHA, items.comments["75"][0])

    def test_already_merged_pr_is_idempotent_for_merge_call(self):
        provider = FakeIntegrationProvider(
            pr_state="closed",
            merged=True,
            merge_commit_sha=MERGE_SHA,
        )
        items = work_items()

        result = sync_integration_merge(
            provider,
            items,
            "75",
            PR_NUMBER,
        )

        self.assertEqual("verified", result["status"])
        self.assertEqual(LifecycleState.INTEGRATION, items.get("75").state)
        self.assertEqual(
            [("exact", "ai/integration", MERGE_SHA)],
            provider.merge_calls,
        )

    def test_unverified_traceability_blocks_verified_result(self):
        merge = FakeIntegrationProvider()
        items = UnverifiedTraceabilityProvider(
            {
                "75": WorkItem(
                    id="75",
                    title="integration merge",
                    state=LifecycleState.REVIEW,
                    provider="memory",
                )
            }
        )

        with self.assertRaisesRegex(
            IntegrationMergeError,
            "Traceability mutation was not read-after-write verified",
        ):
            sync_integration_merge(
                merge,
                items,
                "75",
                PR_NUMBER,
                expected_head_sha=HEAD_SHA,
            )

        self.assertEqual(LifecycleState.REVIEW, items.get("75").state)

    def test_unverified_transition_blocks_verified_result(self):
        merge = FakeIntegrationProvider()
        items = UnverifiedTransitionProvider(
            {
                "75": WorkItem(
                    id="75",
                    title="integration merge",
                    state=LifecycleState.REVIEW,
                    provider="memory",
                )
            }
        )

        with self.assertRaisesRegex(
            IntegrationMergeError,
            "Lifecycle transition mutation was not read-after-write verified",
        ):
            sync_integration_merge(
                merge,
                items,
                "75",
                PR_NUMBER,
                expected_head_sha=HEAD_SHA,
            )

        self.assertEqual(LifecycleState.REVIEW, items.get("75").state)

    def test_cli_writes_canonical_integration_merge_evidence(self):
        merge = FakeIntegrationProvider()
        items = work_items()

        with tempfile.TemporaryDirectory() as temp:
            canonical_path = Path(temp) / "integration-merge-evidence.json"
            argv = [
                "integration_merge.py",
                REPOSITORY,
                "75",
                str(PR_NUMBER),
                "--expected-head-sha",
                HEAD_SHA,
                "--canonical-evidence-output",
                str(canonical_path),
            ]
            with (
                patch.object(
                    integration_merge_module,
                    "GitHubIntegrationMergeProvider",
                    return_value=merge,
                ),
                patch.object(
                    integration_merge_module,
                    "_build_work_item_provider",
                    return_value=items,
                ),
                patch.object(sys, "argv", argv),
            ):
                self.assertEqual(0, integration_merge_module.main())

            canonical = read_and_validate_evidence(canonical_path)
            self.assertEqual("integration-merge", canonical.kind)
            self.assertEqual(MERGE_SHA, canonical.revision)
            self.assertEqual(HEAD_SHA, canonical.result["validation_head_sha"])

    def test_open_pr_with_non_clean_mergeability_is_blocked(self):
        provider = FakeIntegrationProvider(mergeable_state="blocked")
        items = work_items()

        with self.assertRaisesRegex(IntegrationMergeError, "mergeable_state must be clean"):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

        self.assertEqual(LifecycleState.REVIEW, items.get("75").state)
        self.assertEqual([], provider.merge_calls)

    def test_draft_pr_is_blocked(self):
        provider = FakeIntegrationProvider(draft=True)
        items = work_items()

        with self.assertRaisesRegex(IntegrationMergeError, "Draft pull requests"):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

        self.assertEqual([], provider.merge_calls)

    def test_closed_unmerged_pr_is_non_mutating(self):
        provider = FakeIntegrationProvider(pr_state="closed", merged=False)
        items = work_items()

        result = sync_integration_merge(provider, items, "75", PR_NUMBER)

        self.assertEqual("not-merged", result["status"])
        self.assertEqual(LifecycleState.REVIEW, items.get("75").state)
        self.assertEqual([], provider.merge_calls)

    def test_rejects_unprotected_integration(self):
        provider = FakeIntegrationProvider(protected=False)
        items = work_items()

        with self.assertRaisesRegex(IntegrationMergeError, "must remain protected"):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

        self.assertEqual([], provider.merge_calls)

    def test_rejects_head_sha_change_when_expected_sha_is_supplied(self):
        provider = FakeIntegrationProvider(head_sha="4444444444444444444444444444444444444444")
        items = work_items()

        with self.assertRaisesRegex(
            IntegrationMergeError,
            "head SHA changed after validation",
        ):
            sync_integration_merge(
                provider,
                items,
                "75",
                PR_NUMBER,
                expected_head_sha=HEAD_SHA,
            )

        self.assertEqual([], provider.merge_calls)

    def test_rejects_wrong_task_head(self):
        provider = FakeIntegrationProvider(
            head="ai/feature/999-other-task",
        )
        items = work_items()

        with self.assertRaisesRegex(IntegrationMergeError, "task branch for this work item"):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

    def test_rejects_wrong_base(self):
        provider = FakeIntegrationProvider(base="develop")
        items = work_items()

        with self.assertRaisesRegex(IntegrationMergeError, "base does not match"):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

    def test_rejects_open_pr_without_validation_head_sha(self):
        provider = FakeIntegrationProvider()
        items = work_items()

        with self.assertRaisesRegex(
            IntegrationMergeError,
            "exact validation head SHA is required",
        ):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

        self.assertEqual(LifecycleState.REVIEW, items.get("75").state)
        self.assertEqual([], provider.merge_calls)

    def test_rejects_integration_branch_advanced_after_exact_compare(self):
        provider = FakeIntegrationProvider(post_merge_sha=ADVANCED_SHA)
        items = work_items()

        with self.assertRaisesRegex(
            IntegrationMergeError,
            "advanced after exact merge verification",
        ):
            sync_integration_merge(
                provider,
                items,
                "75",
                PR_NUMBER,
                expected_head_sha=HEAD_SHA,
            )

        self.assertEqual(LifecycleState.REVIEW, items.get("75").state)

    def test_rejects_missing_merge_commit(self):
        provider = FakeIntegrationProvider(pr_state="closed", merged=True)
        items = work_items()

        with self.assertRaisesRegex(IntegrationMergeError, "no merge commit SHA"):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

    def test_rejects_merge_commit_not_in_target(self):
        provider = FakeIntegrationProvider(exact_merge=False)
        items = work_items()

        with self.assertRaisesRegex(
            IntegrationMergeError,
            "not exactly equal to integration merge commit",
        ):
            sync_integration_merge(
                provider,
                items,
                "75",
                PR_NUMBER,
                expected_head_sha=HEAD_SHA,
            )

        self.assertEqual(LifecycleState.REVIEW, items.get("75").state)

    def test_rejects_work_item_outside_review(self):
        provider = FakeIntegrationProvider()
        items = work_items(LifecycleState.VERIFICATION)

        with self.assertRaisesRegex(IntegrationMergeError, "requires a work item in review"):
            sync_integration_merge(provider, items, "75", PR_NUMBER)

        self.assertEqual([], provider.merge_calls)

    def test_github_provider_rejects_non_identical_compare_result(self):
        transport = FakeGitHubTransport()
        provider = GitHubIntegrationMergeProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

        self.assertTrue(provider.target_matches_commit("ai/integration", MERGE_SHA))
        transport.comparison = {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
        }
        self.assertFalse(provider.target_matches_commit("ai/integration", MERGE_SHA))


    def test_github_provider_uses_exact_sha_and_squash_merge(self):
        transport = FakeGitHubTransport()
        provider = GitHubIntegrationMergeProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

        pull_request = provider.get_pull_request(PR_NUMBER)
        result = provider.merge_pull_request(
            PR_NUMBER,
            pull_request.head_sha,
        )

        self.assertTrue(result.merged)
        self.assertEqual(MERGE_SHA, result.merge_commit_sha)
        self.assertEqual(
            {"sha": HEAD_SHA, "merge_method": "squash"},
            transport.merge_payload,
        )

        self.assertTrue(
            provider.target_matches_commit("ai/integration", MERGE_SHA)
        )


if __name__ == "__main__":
    unittest.main()
