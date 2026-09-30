import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from delivery import DeliveryError, GitHubPullRequestProvider
from integration_merge import IntegrationMergeError, GitHubIntegrationMergeProvider
from promotion_readiness import (
    BranchSnapshot,
    GitHubPromotionProvider,
    PromotionReadinessError,
)
import promotion_sync as promotion_sync_module
from evidence_contract import read_and_validate_evidence
from promotion_snapshot import GitHubPromotionSnapshotProvider, PromotionSnapshotError
from promotion_sync import (
    GitHubPromotionSyncProvider,
    PromotionPullRequest,
    PromotionSyncError,
    sync_promotion_merge,
)
from work_item_lifecycle import (
    GitHubIssuesProvider,
    LifecycleState,
    MutationEvidence,
    Traceability,
    WorkItem,
    WorkItemLifecycleError,
)


REPOSITORY = "KenlikDev/aegis-engineering-os"
PROMOTION_PR = 123
MERGE_SHA = "1111111111111111111111111111111111111111"
HEAD_SHA = "2222222222222222222222222222222222222222"
TARGET_SHA = "3333333333333333333333333333333333333333"


class FakePromotionProvider:
    def __init__(
        self,
        *,
        state="closed",
        merged=True,
        protected=True,
        exact_merge=True,
        target_sha=MERGE_SHA,
        trace_verified=True,
        transition_verified=True,
        head="ai/1-main-promotion",
        base="main",
        merge_commit_sha=MERGE_SHA,
    ):
        self.repository = REPOSITORY
        self.pull_request = PromotionPullRequest(
            number=PROMOTION_PR,
            url="https://github.com/KenlikDev/aegis-engineering-os/pull/123",
            head=head,
            head_sha=HEAD_SHA,
            base=base,
            base_sha=TARGET_SHA,
            state=state,
            merged=merged,
            merge_commit_sha=merge_commit_sha,
            head_repository=REPOSITORY,
            base_repository=REPOSITORY,
        )
        self.target = BranchSnapshot(
            branch="main",
            sha=TARGET_SHA,
            protected=protected,
        )
        self.exact_merge = exact_merge
        self.target_sha = target_sha
        self.trace_verified = trace_verified
        self.transition_verified = transition_verified
        self.contains_calls = []

    def get_pull_request(self, number):
        if number != PROMOTION_PR:
            raise AssertionError(f"Unexpected PR number: {number}")
        return self.pull_request

    def get_branch(self, branch):
        if branch != "main":
            raise AssertionError(f"Unexpected target: {branch}")
        return BranchSnapshot(
            branch="main",
            sha=self.target_sha,
            protected=self.target.protected,
        )

    def target_matches_commit(self, target_branch, commit_sha):
        self.contains_calls.append((target_branch, commit_sha))
        return self.exact_merge


class FakeWorkItemProvider:
    def __init__(
        self,
        state=LifecycleState.INTEGRATION,
        *,
        trace_verified=True,
        transition_verified=True,
    ):
        self.item = WorkItem(
            id="1",
            title="Promotion task",
            state=state,
            provider="fake",
            provider_url="https://example.test/issues/1",
        )
        self.traceability = []
        self.transitions = []
        self.trace_verified = trace_verified
        self.transition_verified = transition_verified

    def get(self, work_item_id):
        if work_item_id != "1":
            raise AssertionError(f"Unexpected work item: {work_item_id}")
        return self.item

    def attach_traceability(self, work_item_id, traceability):
        self.traceability.append((work_item_id, traceability))
        return MutationEvidence(
            provider="fake",
            operation="attach_traceability",
            work_item_id=work_item_id,
            verified=self.trace_verified,
            reference=traceability.pull_request_url,
        )

    def transition(self, work_item_id, target, *, expected_state=None):
        current = self.item.state
        if expected_state is not None and current != expected_state:
            raise AssertionError(
                f"Expected {expected_state.value}, got {current.value}"
            )
        self.transitions.append((current, target))
        self.item = WorkItem(
            id=self.item.id,
            title=self.item.title,
            state=target,
            provider=self.item.provider,
            provider_url=self.item.provider_url,
        )
        return MutationEvidence(
            provider="fake",
            operation="transition",
            work_item_id=work_item_id,
            state_before=current.value,
            state_after=target.value,
            verified=self.transition_verified,
        )


class FakeGitHubTransport:
    def __init__(self, *, head_repository=REPOSITORY, base_repository=REPOSITORY):
        self.url = None
        self.status = "ahead"
        self.head_repository = head_repository
        self.base_repository = base_repository

    def __call__(self, method, url, headers, payload):
        self.url = url
        if url.endswith(f"/repos/{REPOSITORY}/pulls/{PROMOTION_PR}"):
            return 200, {
                "number": PROMOTION_PR,
                "html_url": "https://github.com/KenlikDev/aegis-engineering-os/pull/123",
                "head": {
                    "ref": "ai/1-main-promotion",
                    "sha": HEAD_SHA,
                    "repo": {"full_name": self.head_repository},
                },
                "base": {
                    "ref": "main",
                    "sha": TARGET_SHA,
                    "repo": {"full_name": self.base_repository},
                },
                "state": "closed",
                "merged_at": "2026-09-28T15:00:00Z",
                "merge_commit_sha": MERGE_SHA,
            }
        return 200, {
            "status": self.status,
            "ahead_by": 1 if self.status == "ahead" else 0,
            "behind_by": 0,
        }


    def test_cli_writes_canonical_promotion_sync_evidence(self):
        provider = FakePromotionProvider()
        work_items = FakeWorkItemProvider()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "promotion-sync.json"
            argv = [
                "promotion_sync.py",
                REPOSITORY,
                "1",
                str(PROMOTION_PR),
                "main",
                "--canonical-evidence-output",
                str(output),
            ]
            with (
                patch.object(
                    promotion_sync_module,
                    "GitHubPromotionSyncProvider",
                    return_value=provider,
                ),
                patch.object(
                    promotion_sync_module,
                    "_build_work_item_provider",
                    return_value=work_items,
                ),
                patch.object(sys, "argv", argv),
            ):
                self.assertEqual(0, promotion_sync_module.main())

            canonical = read_and_validate_evidence(output)
            self.assertEqual("promotion-sync", canonical.kind)
            self.assertEqual(MERGE_SHA, canonical.revision)
            self.assertEqual("promotion:1->main", canonical.subject)

class PromotionSyncTests(unittest.TestCase):
    def test_rejects_fork_origin_before_lifecycle_transition(self):
        provider = FakePromotionProvider()
        provider.pull_request = PromotionPullRequest(
            number=provider.pull_request.number,
            url=provider.pull_request.url,
            head=provider.pull_request.head,
            head_sha=provider.pull_request.head_sha,
            base=provider.pull_request.base,
            base_sha=provider.pull_request.base_sha,
            state=provider.pull_request.state,
            merged=True,
            merge_commit_sha=MERGE_SHA,
            head_repository="attacker/example-fork",
            base_repository=REPOSITORY,
        )

        with self.assertRaisesRegex(
            PromotionSyncError,
            "head and base repositories must match",
        ):
            sync_promotion_merge(
                provider,
                WorkItemProvider(),
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

    def test_github_provider_requires_identical_compare(self):
        transport = FakeGitHubTransport()
        provider = GitHubPromotionSyncProvider(
            REPOSITORY,
            "test-token",
            transport=transport,
            api_base_url="https://api.github.com",
        )

        self.assertFalse(provider.target_matches_commit("main", MERGE_SHA))
        self.assertEqual(
            f"/repos/{REPOSITORY}/compare/main...{MERGE_SHA}",
            transport.url.removeprefix("https://api.github.com"),
        )

        transport.status = "identical"
        self.assertTrue(provider.target_matches_commit("main", MERGE_SHA))

    def test_all_github_providers_reject_untrusted_credential_destination(self):
        invalid_url = "https://api.github.com.attacker.example"
        factories = (
            (GitHubPullRequestProvider, DeliveryError),
            (GitHubIntegrationMergeProvider, IntegrationMergeError),
            (GitHubPromotionSnapshotProvider, PromotionSnapshotError),
            (GitHubPromotionProvider, PromotionReadinessError),
            (GitHubPromotionSyncProvider, PromotionSyncError),
            (GitHubIssuesProvider, WorkItemLifecycleError),
        )

        for provider_class, error_type in factories:
            with self.subTest(provider=provider_class.__name__):
                with self.assertRaises(error_type):
                    provider_class(
                        REPOSITORY,
                        "test-token",
                        api_base_url=invalid_url,
                    )

    def test_successful_merge_advances_integration_to_done(self):
        provider = FakePromotionProvider()
        work_items = FakeWorkItemProvider()

        result = sync_promotion_merge(
            provider,
            work_items,
            "1",
            PROMOTION_PR,
            target_branch="main",
        )

        self.assertEqual("verified", result["status"])
        self.assertEqual("done", result["work_item"]["state_after"])
        self.assertEqual(1, len(work_items.traceability))
        self.assertEqual(
            (LifecycleState.INTEGRATION, LifecycleState.DONE),
            work_items.transitions[0],
        )
        self.assertEqual(
            [("main", MERGE_SHA)],
            provider.contains_calls,
        )

    def test_rejects_non_identical_target_compare(self):
        provider = FakePromotionProvider(exact_merge=False)
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(PromotionSyncError, "not exactly equal to main"):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

        self.assertEqual([], work_items.traceability)
        self.assertEqual([], work_items.transitions)

    def test_rejects_target_advanced_after_exact_compare(self):
        provider = FakePromotionProvider(target_sha="4" * 40)
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(
            PromotionSyncError,
            "advanced after exact merge verification",
        ):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

        self.assertEqual([], work_items.traceability)
        self.assertEqual([], work_items.transitions)

    def test_rejects_unverified_traceability_mutation(self):
        provider = FakePromotionProvider()
        work_items = FakeWorkItemProvider(trace_verified=False)

        with self.assertRaisesRegex(
            PromotionSyncError,
            "traceability mutation was not read-after-write verified",
        ):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

        self.assertEqual([], work_items.transitions)

    def test_rejects_unverified_transition_mutation(self):
        provider = FakePromotionProvider()
        work_items = FakeWorkItemProvider(transition_verified=False)

        with self.assertRaisesRegex(
            PromotionSyncError,
            "lifecycle transition mutation was not read-after-write verified",
        ):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

        self.assertEqual(1, len(work_items.transitions))
        self.assertEqual(
            (LifecycleState.INTEGRATION, LifecycleState.DONE),
            work_items.transitions[0],
        )

    def test_open_pr_is_non_mutating(self):
        provider = FakePromotionProvider(state="open", merged=False)
        work_items = FakeWorkItemProvider()

        result = sync_promotion_merge(
            provider,
            work_items,
            "1",
            PROMOTION_PR,
            target_branch="main",
        )

        self.assertEqual("not-merged", result["status"])
        self.assertEqual(LifecycleState.INTEGRATION, work_items.item.state)
        self.assertEqual([], work_items.traceability)
        self.assertEqual([], work_items.transitions)
        self.assertEqual([], provider.contains_calls)

    def test_rejects_work_item_not_integration(self):
        provider = FakePromotionProvider()
        work_items = FakeWorkItemProvider(state=LifecycleState.REVIEW)

        with self.assertRaisesRegex(PromotionSyncError, "integration state"):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

    def test_rejects_unprotected_target(self):
        provider = FakePromotionProvider(protected=False)
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(PromotionSyncError, "must remain protected"):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

    def test_rejects_wrong_promotion_head(self):
        provider = FakePromotionProvider(head="ai/1-develop-promotion")
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(PromotionSyncError, "deterministic promotion branch"):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

    def test_rejects_wrong_target(self):
        provider = FakePromotionProvider(base="develop")
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(PromotionSyncError, "selected protected target"):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

    def test_rejects_missing_merge_commit(self):
        provider = FakePromotionProvider(merge_commit_sha=None)
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(PromotionSyncError, "no merge commit SHA"):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

    def test_rejects_merge_commit_not_present_in_target(self):
        provider = FakePromotionProvider(exact_merge=False)
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(PromotionSyncError, "not exactly equal to main"):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="main",
            )

        self.assertEqual([], work_items.traceability)
        self.assertEqual([], work_items.transitions)

    def test_rejects_invalid_target_before_provider_calls(self):
        provider = FakePromotionProvider()
        work_items = FakeWorkItemProvider()

        with self.assertRaisesRegex(
            PromotionSyncError,
            "Promotion target must be develop or main",
        ):
            sync_promotion_merge(
                provider,
                work_items,
                "1",
                PROMOTION_PR,
                target_branch="release",
            )

        self.assertEqual([], provider.contains_calls)
        self.assertEqual([], work_items.traceability)
        self.assertEqual([], work_items.transitions)


if __name__ == "__main__":
    unittest.main()
