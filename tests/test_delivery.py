import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from delivery import (  # noqa: E402
    CreatePullRequestRequest,
    DeliveryError,
    GitHubPullRequestProvider,
    MutationEvidence,
    PullRequest,
    create_review_pull_request,
    sync_merged_pull_request,
)
from work_item_lifecycle import (  # noqa: E402
    InMemoryWorkItemProvider,
    LifecycleState,
    WorkItem,
)


REPOSITORY = "KenlikDev/aegis-engineering-os"
ISSUE_URL = "https://github.com/KenlikDev/aegis-engineering-os/issues/60"
PR_URL = "https://github.com/KenlikDev/aegis-engineering-os/pull/60"


class FakeGitHubTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.pull_requests: dict[int, dict] = {}
        self.next_number = 60

    def __call__(self, method, url, headers, payload):  # noqa: ANN001
        path = url.removeprefix("https://api.github.com")
        self.calls.append((method, path, dict(payload) if payload else None))

        if path.startswith(f"/repos/{REPOSITORY}/pulls?"):
            if method != "GET":
                raise AssertionError(f"Unexpected pulls collection method: {method}")
            return 200, list(self.pull_requests.values())

        if path == f"/repos/{REPOSITORY}/pulls" and method == "POST":
            number = self.next_number
            self.next_number += 1
            self.pull_requests[number] = {
                "number": number,
                "title": payload["title"],
                "body": payload["body"],
                "head": {
                    "ref": payload["head"],
                    "repo": {"full_name": REPOSITORY},
                },
                "base": {
                    "ref": payload["base"],
                    "repo": {"full_name": REPOSITORY},
                },
                "state": "open",
                "merged_at": None,
                "draft": payload.get("draft", False),
                "mergeable": True,
                "mergeable_state": "clean",
                "html_url": f"{PR_URL}/{number}",
            }
            return 201, self.pull_requests[number]

        if path.startswith(f"/repos/{REPOSITORY}/pulls/"):
            number = int(path.rsplit("/", 1)[-1])
            if method != "GET" or number not in self.pull_requests:
                raise AssertionError(f"Unexpected PR request: {method} {path}")
            return 200, self.pull_requests[number]

        raise AssertionError(f"Unexpected GitHub request: {method} {path}")


class FakePullRequestProvider:
    def __init__(self, pull_request: PullRequest) -> None:
        self.pull_request = pull_request
        self.created: list[CreatePullRequestRequest] = []

    def find_open(self, head: str, base: str) -> PullRequest | None:
        if (
            self.pull_request.state == "open"
            and not self.pull_request.merged
            and self.pull_request.head == head
            and self.pull_request.base == base
        ):
            return self.pull_request
        return None

    def get(self, pull_request_number: int | str) -> PullRequest:
        if int(pull_request_number) != self.pull_request.number:
            raise AssertionError("Unexpected pull request lookup.")
        return self.pull_request

    def create(self, request: CreatePullRequestRequest) -> MutationEvidence:
        self.created.append(request)
        return MutationEvidence(
            provider="fake",
            operation="create",
            reference="not-a-number-url",
            verified=True,
            identifier=self.pull_request.number,
        )


def review_item_provider() -> InMemoryWorkItemProvider:
    return InMemoryWorkItemProvider(
        {
            "60": WorkItem(
                id="60",
                title="delivery",
                state=LifecycleState.REVIEW,
                provider="memory",
                provider_url=ISSUE_URL,
            )
        }
    )


def request() -> CreatePullRequestRequest:
    return CreatePullRequestRequest(
        repository=REPOSITORY,
        head="ai/feature/60-pull-request-lifecycle",
        base="ai/integration",
        title="feat(delivery): add pull-request lifecycle bridge",
        body="Closes #60.",
    )


class UnverifiedCreateProvider(FakePullRequestProvider):
    def create(self, request):
        self.created.append(request)
        return MutationEvidence(
            provider="fake",
            operation="create",
            reference="not-a-number-url",
            verified=False,
            identifier=self.pull_request.number,
        )


class UnverifiedTraceabilityProvider(InMemoryWorkItemProvider):
    def attach_traceability(self, work_item_id, traceability):
        return MutationEvidence(
            provider="memory",
            operation="comment",
            reference="not-verified",
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
            reference=current.provider_url or "not-verified",
            verified=False,
        )


class DeliveryTests(unittest.TestCase):
    def test_create_rejects_protected_target(self) -> None:
        provider = GitHubPullRequestProvider(
            REPOSITORY,
            "secret-token",
            transport=lambda *args: (_ for _ in ()).throw(
                AssertionError("network must not be reached")
            ),
        )
        with self.assertRaises(DeliveryError):
            provider.create(
                CreatePullRequestRequest(
                    repository=REPOSITORY,
                    head="ai/feature/60-pull-request-lifecycle",
                    base="develop",
                    title="test",
                    body="",
                )
            )

    def test_create_rejects_non_aegis_head(self) -> None:
        provider = GitHubPullRequestProvider(
            REPOSITORY,
            "secret-token",
            transport=lambda *args: (_ for _ in ()).throw(
                AssertionError("network must not be reached")
            ),
        )
        with self.assertRaises(DeliveryError):
            provider.create(
                CreatePullRequestRequest(
                    repository=REPOSITORY,
                    head="feature/local",
                    base="ai/integration",
                    title="test",
                    body="",
                )
            )

    def test_create_rejects_unverified_pull_request_mutation(self) -> None:
        work_items = review_item_provider()
        pr_provider = UnverifiedCreateProvider(
            PullRequest(
                number=60,
                title="test",
                body="",
                head=request().head,
                base=request().base,
                state="open",
                merged=False,
                draft=False,
                mergeable=True,
                mergeable_state="clean",
                url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
            )
        )

        with self.assertRaisesRegex(
            DeliveryError,
            "creation mutation was not read-after-write verified",
        ):
            create_review_pull_request(
                pr_provider,
                work_items,
                "60",
                request(),
            )

    def test_create_rejects_unverified_traceability_mutation(self) -> None:
        work_items = UnverifiedTraceabilityProvider(
            {
                "60": WorkItem(
                    id="60",
                    title="delivery",
                    state=LifecycleState.REVIEW,
                    provider="memory",
                    provider_url=ISSUE_URL,
                )
            }
        )
        pr_provider = FakePullRequestProvider(
            PullRequest(
                number=60,
                title="test",
                body="",
                head=request().head,
                base=request().base,
                state="open",
                merged=False,
                draft=False,
                mergeable=True,
                mergeable_state="clean",
                url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
            )
        )

        with self.assertRaisesRegex(
            DeliveryError,
            "traceability mutation was not read-after-write verified",
        ):
            create_review_pull_request(
                pr_provider,
                work_items,
                "60",
                request(),
            )

    def test_create_requires_review_work_item(self) -> None:
        provider = InMemoryWorkItemProvider(
            {
                "60": WorkItem(
                    id="60",
                    title="delivery",
                    state=LifecycleState.VERIFICATION,
                    provider="memory",
                )
            }
        )
        pr_provider = FakePullRequestProvider(
            PullRequest(
                number=60,
                title="test",
                body="",
                head=request().head,
                base=request().base,
                state="open",
                merged=False,
                draft=False,
                mergeable=True,
                mergeable_state="clean",
                url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
            )
        )
        with self.assertRaises(DeliveryError):
            create_review_pull_request(
                pr_provider,
                provider,
                "60",
                request(),
            )

    def test_create_uses_provider_identifier_not_url_parsing(self) -> None:
        work_items = review_item_provider()
        pr_provider = FakePullRequestProvider(
            PullRequest(
                number=60,
                title="test",
                body="",
                head=request().head,
                base=request().base,
                state="open",
                merged=False,
                draft=False,
                mergeable=True,
                mergeable_state="clean",
                url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
            )
        )

        result = create_review_pull_request(
            pr_provider,
            work_items,
            "60",
            request(),
        )
        self.assertEqual(60, result["pull_request"]["number"])
        self.assertEqual(1, len(pr_provider.created))
        self.assertEqual(LifecycleState.REVIEW, work_items.get("60").state)
        self.assertIn(request().head, work_items.comments["60"][0])

    def test_github_provider_creates_and_reads_back_pull_request(self) -> None:
        transport = FakeGitHubTransport()
        provider = GitHubPullRequestProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )
        evidence = provider.create(request())
        self.assertTrue(evidence.verified)
        self.assertEqual(60, evidence.identifier)
        self.assertEqual("create", evidence.operation)

        methods = [(method, path) for method, path, _ in transport.calls]
        self.assertIn(("POST", f"/repos/{REPOSITORY}/pulls"), methods)
        self.assertIn(("GET", f"/repos/{REPOSITORY}/pulls/60"), methods)

    def test_github_provider_reuses_existing_open_pull_request(self) -> None:
        transport = FakeGitHubTransport()
        transport.pull_requests[60] = {
            "number": 60,
            "title": "existing",
            "body": "",
            "head": {
                "ref": request().head,
                "repo": {"full_name": REPOSITORY},
            },
            "base": {
                "ref": request().base,
                "repo": {"full_name": REPOSITORY},
            },
            "state": "open",
            "merged_at": None,
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "html_url": PR_URL,
        }
        provider = GitHubPullRequestProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

        evidence = provider.create(request())
        self.assertEqual("reuse_existing", evidence.operation)
        self.assertEqual(60, evidence.identifier)
        self.assertNotIn(
            ("POST", f"/repos/{REPOSITORY}/pulls"),
            [(method, path) for method, path, _ in transport.calls],
        )

    def test_github_provider_accepts_null_pull_request_body(self) -> None:
        transport = FakeGitHubTransport()
        transport.pull_requests[60] = {
            "number": 60,
            "title": "nullable body",
            "body": None,
            "head": {
                "ref": request().head,
                "repo": {"full_name": REPOSITORY},
            },
            "base": {
                "ref": request().base,
                "repo": {"full_name": REPOSITORY},
            },
            "state": "open",
            "merged_at": None,
            "draft": False,
            "mergeable": None,
            "mergeable_state": "unknown",
            "html_url": PR_URL,
        }
        provider = GitHubPullRequestProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

        pr = provider.get(60)
        self.assertEqual("", pr.body)

    def test_github_provider_rejects_fork_origin(self) -> None:
        transport = FakeGitHubTransport()
        transport.pull_requests[60] = {
            "number": 60,
            "title": "fork-origin",
            "body": "",
            "head": {
                "ref": request().head,
                "repo": {"full_name": "attacker/example-fork"},
            },
            "base": {
                "ref": request().base,
                "repo": {"full_name": REPOSITORY},
            },
            "state": "open",
            "merged_at": None,
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "html_url": PR_URL,
        }
        provider = GitHubPullRequestProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

        with self.assertRaisesRegex(
            DeliveryError,
            "repositories must match",
        ):
            provider.get(60)

    def test_github_provider_parses_merged_state(self) -> None:
        transport = FakeGitHubTransport()
        transport.pull_requests[60] = {
            "number": 60,
            "title": "merged",
            "body": "",
            "head": {
                "ref": request().head,
                "repo": {"full_name": REPOSITORY},
            },
            "base": {
                "ref": request().base,
                "repo": {"full_name": REPOSITORY},
            },
            "state": "closed",
            "merged_at": "2026-09-28T14:00:00Z",
            "draft": False,
            "mergeable": False,
            "mergeable_state": "unknown",
            "html_url": PR_URL,
        }
        provider = GitHubPullRequestProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

        pr = provider.get(60)
        self.assertTrue(pr.merged)
        self.assertFalse(pr.mergeable)
        self.assertEqual("unknown", pr.mergeable_state)

    def test_sync_merge_does_not_change_work_item_before_actual_merge(self) -> None:
        work_items = review_item_provider()
        pr = PullRequest(
            number=60,
            title="test",
            body="",
            head=request().head,
            base="ai/integration",
            state="open",
            merged=False,
            draft=False,
            mergeable=True,
            mergeable_state="clean",
            url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
        )
        pr_provider = FakePullRequestProvider(pr)

        result = sync_merged_pull_request(
            pr_provider,
            work_items,
            "60",
            60,
            integration_branch="ai/integration",
            expected_head=request().head,
        )
        self.assertEqual("not-merged", result["status"])
        self.assertEqual(LifecycleState.REVIEW, work_items.get("60").state)

    def test_sync_merge_advances_only_after_verified_merge(self) -> None:
        work_items = review_item_provider()
        pr = PullRequest(
            number=60,
            title="test",
            body="",
            head=request().head,
            base="ai/integration",
            state="closed",
            merged=True,
            draft=False,
            mergeable=True,
            mergeable_state="clean",
            url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
        )
        pr_provider = FakePullRequestProvider(pr)

        result = sync_merged_pull_request(
            pr_provider,
            work_items,
            "60",
            60,
            integration_branch="ai/integration",
            expected_head=request().head,
        )
        self.assertEqual("verified", result["status"])
        self.assertEqual(LifecycleState.INTEGRATION, work_items.get("60").state)

    def test_sync_merge_rejects_unverified_transition_mutation(self) -> None:
        work_items = UnverifiedTransitionProvider(
            {
                "60": WorkItem(
                    id="60",
                    title="delivery",
                    state=LifecycleState.REVIEW,
                    provider="memory",
                    provider_url=ISSUE_URL,
                )
            }
        )
        pr_provider = FakePullRequestProvider(
            PullRequest(
                number=60,
                title="test",
                body="",
                head=request().head,
                base="ai/integration",
                state="closed",
                merged=True,
                draft=False,
                mergeable=True,
                mergeable_state="clean",
                url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
            )
        )

        with self.assertRaisesRegex(
            DeliveryError,
            "Lifecycle transition mutation was not read-after-write verified",
        ):
            sync_merged_pull_request(
                pr_provider,
                work_items,
                "60",
                60,
                integration_branch="ai/integration",
                expected_head=request().head,
            )

        self.assertEqual(LifecycleState.REVIEW, work_items.get("60").state)

    def test_sync_merge_rejects_wrong_head(self) -> None:
        work_items = review_item_provider()
        pr_provider = FakePullRequestProvider(
            PullRequest(
                number=60,
                title="test",
                body="",
                head="ai/feature/other",
                base="ai/integration",
                state="closed",
                merged=True,
                draft=False,
                mergeable=True,
                mergeable_state="clean",
                url=PR_URL,
                head_repository=REPOSITORY,
                base_repository=REPOSITORY,
            )
        )
        with self.assertRaises(DeliveryError):
            sync_merged_pull_request(
                pr_provider,
                work_items,
                "60",
                60,
                integration_branch="ai/integration",
                expected_head=request().head,
            )


if __name__ == "__main__":
    unittest.main()
