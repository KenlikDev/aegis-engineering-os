import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from delivery import PullRequest
from integration_delivery import (  # noqa: E402
    IntegrationDeliveryError,
    IntegrationDeliveryRequest,
    deliver_to_integration,
)
from integration_merge import IntegrationPullRequest, MergeResult
from promotion_readiness import BranchSnapshot, ValidationRun
from work_item_lifecycle import (
    InMemoryWorkItemProvider,
    LifecycleState,
    MutationEvidence,
    Traceability,
    WorkItem,
)

REPOSITORY = "KenlikDev/aegis-engineering-os"
HEAD = "1111111111111111111111111111111111111111"
MERGE = "2222222222222222222222222222222222222222"
INTEGRATION = "3333333333333333333333333333333333333333"
WORK_ITEM = "77"
PR_NUMBER = 770


def work_items(state=LifecycleState.REVIEW):
    return InMemoryWorkItemProvider(
        {
            WORK_ITEM: WorkItem(
                id=WORK_ITEM,
                title="integration delivery",
                state=state,
                provider="memory",
            )
        }
    )


class FakePullRequestProvider:
    def __init__(self):
        self.created = []
        self.pull_request = PullRequest(
            number=PR_NUMBER,
            title="feat",
            body="",
            head=f"ai/feature/{WORK_ITEM}-integration",
            base="ai/integration",
            state="open",
            merged=False,
            draft=False,
            mergeable=True,
            mergeable_state="clean",
            url=f"https://github.com/KenlikDev/aegis-engineering-os/pull/{PR_NUMBER}",
        )

    def find_open(self, head, base):
        if self.pull_request.head == head and self.pull_request.base == base:
            return self.pull_request
        return None

    def get(self, number):
        return self.pull_request

    def create(self, request):
        self.created.append(request)
        return MutationEvidence(
            provider="fake",
            operation="create",
            work_item_id=WORK_ITEM,
            reference=self.pull_request.url,
            verified=True,
            identifier=PR_NUMBER,
        )


class FakeMergeProvider:
    repository = REPOSITORY

    def __init__(self):
        self.pull_request = IntegrationPullRequest(
            number=PR_NUMBER,
            url=f"https://github.com/KenlikDev/aegis-engineering-os/pull/{PR_NUMBER}",
            head=f"ai/feature/{WORK_ITEM}-integration",
            head_sha=HEAD,
            base="ai/integration",
            state="open",
            merged=False,
            draft=False,
            mergeable_state="clean",
            merge_commit_sha=None,
        )
        self.integration = BranchSnapshot(
            branch="ai/integration",
            sha=INTEGRATION,
            protected=True,
        )
        self.merge_calls = []

    def get_pull_request(self, number):
        return self.pull_request

    def get_branch(self, branch):
        return self.integration

    def target_contains_commit(self, branch, sha):
        return sha == MERGE and branch == "ai/integration"

    def merge_pull_request(self, number, expected_head_sha):
        self.merge_calls.append((number, expected_head_sha))
        self.pull_request = IntegrationPullRequest(
            number=PR_NUMBER,
            url=self.pull_request.url,
            head=self.pull_request.head,
            head_sha=HEAD,
            base="ai/integration",
            state="closed",
            merged=True,
            draft=False,
            mergeable_state="unknown",
            merge_commit_sha=MERGE,
        )
        return MergeResult(merged=True, merge_commit_sha=MERGE)


class FakeValidationProvider:
    repository = REPOSITORY

    def __init__(self, validation=True):
        self.validation = validation
        self.calls = []

    def latest_successful_validation(self, workflow, head_sha):
        self.calls.append((workflow, head_sha))
        if not self.validation:
            return None
        return ValidationRun(
            id=99,
            workflow=workflow,
            status="completed",
            conclusion="success",
            head_sha=head_sha,
            url="https://github.com/KenlikDev/aegis-engineering-os/actions/runs/99",
        )


class IntegrationDeliveryTests(unittest.TestCase):
    def request(self):
        return IntegrationDeliveryRequest(
            repository=REPOSITORY,
            work_item_id=WORK_ITEM,
            head=f"ai/feature/{WORK_ITEM}-integration",
            title="feat: deliver integration",
            body="Closes #77.",
        )

    def providers(self, validation=True):
        return (
            FakePullRequestProvider(),
            FakeMergeProvider(),
            FakeValidationProvider(validation),
            work_items(),
        )

    def test_composes_pr_validation_and_merge(self):
        pr, merge, validation, items = self.providers()

        result = deliver_to_integration(
            pr,
            merge,
            validation,
            items,
            self.request(),
        )

        self.assertEqual("verified", result["status"])
        self.assertEqual("integration", items.get(WORK_ITEM).state)
        self.assertEqual([(PR_NUMBER, HEAD)], merge.merge_calls)
        self.assertEqual(
            [(".github/workflows/validate.yml", HEAD)],
            validation.calls,
        )
        self.assertEqual(MERGE, result["pull_request"]["merge_commit_sha"])

    def test_blocks_without_exact_head_validation(self):
        pr, merge, validation, items = self.providers(validation=False)

        with self.assertRaisesRegex(
            IntegrationDeliveryError,
            "exact task PR head SHA",
        ):
            deliver_to_integration(pr, merge, validation, items, self.request())

        self.assertEqual([], merge.merge_calls)
        self.assertEqual(LifecycleState.REVIEW, items.get(WORK_ITEM).state)

    def test_rejects_non_review_work_item(self):
        pr, merge, validation, items = self.providers()
        items = work_items(LifecycleState.VERIFICATION)

        with self.assertRaisesRegex(IntegrationDeliveryError, "in review"):
            deliver_to_integration(pr, merge, validation, items, self.request())

        self.assertEqual([], merge.merge_calls)

    def test_rejects_draft_request(self):
        pr, merge, validation, items = self.providers()
        request = IntegrationDeliveryRequest(
            repository=REPOSITORY,
            work_item_id=WORK_ITEM,
            head=self.request().head,
            title="feat",
            body="",
            draft=True,
        )

        with self.assertRaisesRegex(IntegrationDeliveryError, "does not accept draft"):
            deliver_to_integration(pr, merge, validation, items, request)

    def test_refuses_head_changed_after_validation(self):
        pr, merge, validation, items = self.providers()

        original_get = merge.get_pull_request
        calls = {"count": 0}

        def changing_get(number):
            value = original_get(number)
            calls["count"] += 1
            if calls["count"] >= 2:
                value = IntegrationPullRequest(
                    number=value.number,
                    url=value.url,
                    head=value.head,
                    head_sha="4444444444444444444444444444444444444444",
                    base=value.base,
                    state=value.state,
                    merged=value.merged,
                    draft=value.draft,
                    mergeable_state=value.mergeable_state,
                    merge_commit_sha=value.merge_commit_sha,
                )
            return value

        merge.get_pull_request = changing_get

        with self.assertRaisesRegex(
            IntegrationDeliveryError,
            "head SHA changed after validation",
        ):
            deliver_to_integration(pr, merge, validation, items, self.request())

        self.assertEqual([], merge.merge_calls)

    def test_already_merged_path_skips_new_validation(self):
        pr, merge, validation, items = self.providers()
        merge.pull_request = IntegrationPullRequest(
            number=PR_NUMBER,
            url=merge.pull_request.url,
            head=merge.pull_request.head,
            head_sha=HEAD,
            base="ai/integration",
            state="closed",
            merged=True,
            draft=False,
            mergeable_state="unknown",
            merge_commit_sha=MERGE,
        )

        result = deliver_to_integration(
            pr,
            merge,
            validation,
            items,
            self.request(),
        )

        self.assertEqual("verified", result["status"])
        self.assertEqual([], validation.calls)
        self.assertEqual([], merge.merge_calls)
        self.assertEqual(LifecycleState.INTEGRATION, items.get(WORK_ITEM).state)


if __name__ == "__main__":
    unittest.main()
