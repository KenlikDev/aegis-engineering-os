import io
import sys
from contextlib import redirect_stdout
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from work_item_lifecycle import (  # noqa: E402
    GitHubIssuesProvider,
    InMemoryWorkItemProvider,
    LifecycleState,
    Traceability,
    WorkItem,
    WorkItemLifecycleError,
    MutationEvidence,
    _print_evidence,
    render_traceability_comment,
    LIFECYCLE_LOCK_HEADER,
    require_verified_mutation,
    validate_transition,
)


ISSUE_URL = "https://github.com/KenlikDev/aegis-engineering-os/issues/53"


class FakeGitHubTransport:
    def __init__(self) -> None:
        self.state = "open"
        self.state_reason = None
        self.labels: set[str] = set()
        self.comments: dict[int, str] = {}
        self.next_comment_id = 100
        self.calls: list[tuple[str, str, dict | None]] = []
        self.integration_sha = "1" * 40
        self.integration_tree_sha = "2" * 40
        self.git_commits: dict[str, dict[str, object]] = {
            self.integration_sha: {
                "tree": self.integration_tree_sha,
                "parents": [],
                "message": "integration base",
            }
        }
        self.next_git_sha = 4
        self.lock_sha: str | None = None
        self.lock_conflict = False
        self.mutate_after_first_issue_get = False
        self.release_race = False
        self.transition_error = False
        self.issue_get_count = 0

    def seed_stale_lock(self) -> None:
        stale_sha = "3" * 40
        self.git_commits[stale_sha] = {
            "tree": self.integration_tree_sha,
            "parents": [self.integration_sha],
            "message": "\n".join(
                (
                    LIFECYCLE_LOCK_HEADER,
                    "work-item: 53",
                    "mode: held",
                    "owner: 12345678-1234-5678-1234-567812345678",
                    "expires-at: 2000-01-01T00:00:00Z",
                )
            ),
        }
        self.lock_sha = stale_sha

    def _new_git_commit(
        self,
        *,
        parent_sha: str,
        message: str,
    ) -> str:
        sha = f"{self.next_git_sha:040x}"
        self.next_git_sha += 1
        self.git_commits[sha] = {
            "tree": self.integration_tree_sha,
            "parents": [parent_sha],
            "message": message,
        }
        return sha

    def __call__(self, method, url, headers, payload):  # noqa: ANN001
        path = url.removeprefix("https://api.github.com")
        self.calls.append((method, path, dict(payload) if payload else None))

        if path == "/repos/KenlikDev/aegis-engineering-os/git/ref/heads/ai/integration":
            return 200, {"object": {"sha": self.integration_sha}}

        if path == "/repos/KenlikDev/aegis-engineering-os/git/ref/aegis/locks/work-item/53":
            if method == "GET":
                if self.lock_sha is None:
                    return 404, {}
                return 200, {"object": {"sha": self.lock_sha}}
            if method == "PATCH":
                if self.lock_conflict:
                    competitor = self._new_git_commit(
                        parent_sha=self.lock_sha or self.integration_sha,
                        message="\n".join(
                            (
                                LIFECYCLE_LOCK_HEADER,
                                "work-item: 53",
                                "mode: held",
                                "owner: 87654321-4321-8765-4321-876543218765",
                                "expires-at: 9999-01-01T00:00:00Z",
                            )
                        ),
                    )
                    self.lock_sha = competitor
                    self.lock_conflict = False
                    return 409, {}
                new_sha = payload["sha"]
                if (
                    self.release_race
                    and "mode: free" in self.git_commits[new_sha]["message"]
                ):
                    competitor = self._new_git_commit(
                        parent_sha=self.lock_sha or self.integration_sha,
                        message="\n".join(
                            (
                                LIFECYCLE_LOCK_HEADER,
                                "work-item: 53",
                                "mode: held",
                                "owner: 87654321-4321-8765-4321-876543218765",
                                "expires-at: 9999-01-01T00:00:00Z",
                            )
                        ),
                    )
                    self.lock_sha = competitor
                    self.release_race = False
                    return 409, {}
                parents = self.git_commits[new_sha]["parents"]
                if parents != [self.lock_sha]:
                    return 409, {}
                self.lock_sha = new_sha
                return 200, {"object": {"sha": new_sha}}

        if path == "/repos/KenlikDev/aegis-engineering-os/git/commits" and method == "POST":
            new_sha = self._new_git_commit(
                parent_sha=payload["parents"][0],
                message=payload["message"],
            )
            return 201, {"sha": new_sha}

        if path == "/repos/KenlikDev/aegis-engineering-os/git/refs" and method == "POST":
            if self.lock_sha is not None:
                return 409, {}
            self.lock_sha = payload["sha"]
            return 201, {"ref": payload["ref"], "object": {"sha": self.lock_sha}}

        if path.startswith("/repos/KenlikDev/aegis-engineering-os/git/commits/") and method == "GET":
            commit_sha = path.rsplit("/", 1)[-1]
            commit = self.git_commits.get(commit_sha)
            if commit is None:
                return 404, {}
            return 200, {
                "sha": commit_sha,
                "tree": {"sha": commit["tree"]},
                "parents": [{"sha": parent} for parent in commit["parents"]],
                "message": commit["message"],
            }

        if path == "/repos/KenlikDev/aegis-engineering-os/issues/53":
            if method == "GET":
                self.issue_get_count += 1
                if self.mutate_after_first_issue_get and self.issue_get_count == 1:
                    self.labels.discard("aegis:status:review")
                    self.labels.add("aegis:status:verification")
                return 200, {
                    "number": 53,
                    "title": "test work item",
                    "state": self.state,
                    "state_reason": self.state_reason,
                    "html_url": ISSUE_URL,
                    "labels": [{"name": name} for name in sorted(self.labels)],
                }
            if method == "PATCH":
                if self.transition_error:
                    return 500, {}
                self.state = payload["state"]
                self.labels = set(payload["labels"])
                return 200, {"ok": True}

        if path.startswith("/repos/KenlikDev/aegis-engineering-os/labels/"):
            label_name = path.rsplit("/", 1)[-1].replace("%3A", ":")
            if method == "GET":
                return (200, {"name": label_name}) if label_name in self.labels else (404, {})
            raise AssertionError(f"Unexpected label endpoint: {method} {path}")

        if path == "/repos/KenlikDev/aegis-engineering-os/labels":
            if method == "POST":
                self.labels.add(payload["name"])
                return 201, {"name": payload["name"]}
            raise AssertionError(f"Unexpected labels endpoint: {method} {path}")

        if path == "/repos/KenlikDev/aegis-engineering-os/issues/53/comments":
            self.next_comment_id += 1
            comment_id = self.next_comment_id
            self.comments[comment_id] = payload["body"]
            return 201, {
                "id": comment_id,
                "html_url": f"https://github.com/KenlikDev/aegis-engineering-os/issues/53#issuecomment-{comment_id}",
            }

        if path.startswith("/repos/KenlikDev/aegis-engineering-os/issues/comments/"):
            comment_id = int(path.rsplit("/", 1)[-1])
            return 200, {
                "id": comment_id,
                "body": self.comments[comment_id],
            }

        raise AssertionError(f"Unexpected request: {method} {path}")


class WorkItemLifecycleTests(unittest.TestCase):
    def test_require_verified_mutation_rejects_unverified_evidence(self) -> None:
        evidence = MutationEvidence(
            provider="memory",
            operation="transition",
            work_item_id="53",
            verified=False,
        )
        with self.assertRaisesRegex(
            WorkItemLifecycleError,
            "was not read-after-write verified",
        ):
            require_verified_mutation(evidence, "Test transition")

    def test_lifecycle_cli_cannot_print_unverified_mutation_as_verified(self) -> None:
        evidence = MutationEvidence(
            provider="memory",
            operation="comment",
            work_item_id="53",
            verified=False,
        )
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(
                WorkItemLifecycleError,
                "Lifecycle comment mutation was not read-after-write verified",
            ):
                _print_evidence(evidence)

    def test_transition_matrix_rejects_skips_and_terminal_changes(self) -> None:
        validate_transition(LifecycleState.INTAKE, LifecycleState.PLANNED)
        with self.assertRaises(WorkItemLifecycleError):
            validate_transition(LifecycleState.INTAKE, LifecycleState.REVIEW)
        with self.assertRaises(WorkItemLifecycleError):
            validate_transition(LifecycleState.DONE, LifecycleState.PLANNED)

    def test_blocked_state_requires_recorded_resume_target(self) -> None:
        with self.assertRaises(WorkItemLifecycleError):
            validate_transition(LifecycleState.BLOCKED, LifecycleState.IN_PROGRESS)

        validate_transition(
            LifecycleState.BLOCKED,
            LifecycleState.REVIEW,
            resume_state=LifecycleState.REVIEW,
        )
        with self.assertRaises(WorkItemLifecycleError):
            validate_transition(
                LifecycleState.BLOCKED,
                LifecycleState.PLANNED,
                resume_state=LifecycleState.REVIEW,
            )

    def test_traceability_comment_is_deterministic_and_validated(self) -> None:
        body = render_traceability_comment(
            Traceability(
                branch="ai/feature/53-work-item-lifecycle",
                pull_request_url="https://github.com/KenlikDev/aegis-engineering-os/pull/53",
                evidence_ref="artifacts/aegis-execution.json",
                conversation_id="12345678-1234-5678-1234-567812345678",
            )
        )
        self.assertIn("<!-- aegis:traceability:v1 -->", body)
        self.assertIn("ai/feature/53-work-item-lifecycle", body)
        self.assertIn("artifacts/aegis-execution.json", body)

    def test_traceability_rejects_unsafe_branch_and_url(self) -> None:
        with self.assertRaises(WorkItemLifecycleError):
            Traceability(branch="main").validate()
        with self.assertRaises(WorkItemLifecycleError):
            Traceability(
                pull_request_url="http://github.com/KenlikDev/aegis-engineering-os/pull/53"
            ).validate()
        with self.assertRaises(WorkItemLifecycleError):
            Traceability(
                conversation_id="not-a-uuid"
            ).validate()

    def test_github_get_defaults_open_unlabeled_issue_to_intake(self) -> None:
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=FakeGitHubTransport(),
        )
        item = provider.get("53")
        self.assertEqual(LifecycleState.INTAKE, item.state)
        self.assertEqual("github-issues", item.provider)
        self.assertEqual(ISSUE_URL, item.provider_url)

    def test_github_get_rejects_closed_unlabeled_issue(self) -> None:
        transport = FakeGitHubTransport()
        transport.state = "closed"
        transport.state_reason = "completed"
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )
        with self.assertRaisesRegex(
            WorkItemLifecycleError,
            "closed without an Aegis status label",
        ):
            provider.get("53")

    def test_github_transition_creates_and_verifies_status_label(self) -> None:
        transport = FakeGitHubTransport()
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )

        evidence = provider.transition("53", LifecycleState.PLANNED)
        self.assertTrue(evidence.verified)
        self.assertEqual("intake", evidence.state_before)
        self.assertEqual("planned", evidence.state_after)
        self.assertIn("aegis:status:planned", transport.labels)
        patch_calls = [
            payload
            for method, path, payload in transport.calls
            if method == "PATCH" and path.endswith("/issues/53")
        ]
        self.assertEqual(1, len(patch_calls))
        self.assertEqual("open", patch_calls[0]["state"])

    def test_github_blocked_transition_persists_resume_target(self) -> None:
        transport = FakeGitHubTransport()
        transport.labels.add("aegis:status:in_progress")
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )

        evidence = provider.transition("53", LifecycleState.BLOCKED)
        self.assertEqual("in_progress", evidence.state_before)
        self.assertEqual("blocked", evidence.state_after)
        self.assertIn("aegis:resume:in_progress", transport.labels)

        evidence = provider.transition(
            "53",
            LifecycleState.IN_PROGRESS,
            expected_state=LifecycleState.BLOCKED,
        )
        self.assertEqual("blocked", evidence.state_before)
        self.assertEqual("in_progress", evidence.state_after)
        self.assertNotIn("aegis:resume:in_progress", transport.labels)

    def test_github_done_closes_issue_and_verifies_terminal_state(self) -> None:
        transport = FakeGitHubTransport()
        transport.labels.add("aegis:status:integration")
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )
        evidence = provider.transition(
            "53",
            LifecycleState.DONE,
            expected_state=LifecycleState.INTEGRATION,
        )
        self.assertEqual("done", evidence.state_after)
        self.assertEqual("closed", transport.state)
        self.assertIn("aegis:status:done", transport.labels)

    def test_github_transition_rechecks_expected_state_inside_lock(self) -> None:
        transport = FakeGitHubTransport()
        transport.labels.add("aegis:status:review")
        transport.mutate_after_first_issue_get = True
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )
        with self.assertRaisesRegex(
            WorkItemLifecycleError,
            "state changed concurrently",
        ):
            provider.transition(
                "53",
                LifecycleState.INTEGRATION,
                expected_state=LifecycleState.REVIEW,
            )
        patch_calls = [
            payload
            for method, path, payload in transport.calls
            if method == "PATCH" and path.endswith("/issues/53")
        ]
        self.assertEqual([], patch_calls)

    def test_github_transition_fails_closed_on_atomic_lock_conflict(self) -> None:
        transport = FakeGitHubTransport()
        transport.labels.add("aegis:status:review")
        transport.seed_stale_lock()
        transport.lock_conflict = True
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )
        with self.assertRaisesRegex(
            WorkItemLifecycleError,
            "held by|changed concurrently",
        ):
            provider.transition(
                "53",
                LifecycleState.INTEGRATION,
                expected_state=LifecycleState.REVIEW,
            )
        patch_calls = [
            payload
            for method, path, payload in transport.calls
            if method == "PATCH" and path.endswith("/issues/53")
        ]
        self.assertEqual([], patch_calls)

    def test_verified_transition_survives_release_race_without_overwriting_competitor(self) -> None:
        transport = FakeGitHubTransport()
        transport.release_race = True
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )

        evidence = provider.transition("53", LifecycleState.PLANNED)

        self.assertTrue(evidence.verified)
        self.assertEqual(LifecycleState.PLANNED, provider.get("53").state)
        competitor = transport.git_commits[transport.lock_sha]
        self.assertIn(
            "owner: 87654321-4321-8765-4321-876543218765",
            competitor["message"],
        )

    def test_transition_error_is_preserved_when_lock_cleanup_also_fails(self) -> None:
        transport = FakeGitHubTransport()
        transport.release_race = True
        transport.transition_error = True
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )

        with self.assertRaisesRegex(
            WorkItemLifecycleError,
            "Unable to transition GitHub issue #53; HTTP 500",
        ):
            provider.transition("53", LifecycleState.PLANNED)

    def test_github_transition_rejects_concurrent_state_change(self) -> None:
        transport = FakeGitHubTransport()
        transport.labels.add("aegis:status:review")
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )
        with self.assertRaises(WorkItemLifecycleError):
            provider.transition(
                "53",
                LifecycleState.INTEGRATION,
                expected_state=LifecycleState.VERIFICATION,
            )

    def test_github_comment_uses_read_after_write_verification(self) -> None:
        transport = FakeGitHubTransport()
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )
        evidence = provider.comment("53", "Aegis verification evidence.")
        self.assertTrue(evidence.verified)
        self.assertIsNotNone(evidence.reference)
        self.assertEqual("Aegis verification evidence.", transport.comments[101])

    def test_github_traceability_delegates_to_comment_boundary(self) -> None:
        transport = FakeGitHubTransport()
        provider = GitHubIssuesProvider(
            "KenlikDev/aegis-engineering-os",
            "test-token",
            transport=transport,
        )
        evidence = provider.attach_traceability(
            "53",
            Traceability(branch="ai/fix/53-work-item-lifecycle"),
        )
        self.assertTrue(evidence.verified)
        self.assertIn(
            "<!-- aegis:traceability:v1 -->",
            transport.comments[101],
        )

    def test_in_memory_provider_preserves_blocked_resume_state(self) -> None:
        provider = InMemoryWorkItemProvider(
            {
                "53": WorkItem(
                    id="53",
                    title="test",
                    state=LifecycleState.VERIFICATION,
                    provider="memory",
                )
            }
        )
        provider.transition("53", LifecycleState.BLOCKED)
        self.assertEqual(
            LifecycleState.VERIFICATION,
            provider.get("53").resume_state,
        )
        provider.transition("53", LifecycleState.VERIFICATION)
        self.assertEqual(LifecycleState.VERIFICATION, provider.get("53").state)


if __name__ == "__main__":
    unittest.main()
