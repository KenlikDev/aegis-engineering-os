import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from promotion_snapshot import (  # noqa: E402
    GitHubPromotionSnapshotProvider,
    PromotionSnapshotError,
    PromotionSnapshotRequest,
    prepare_promotion_snapshot,
)

REPOSITORY = "KenlikDev/aegis-engineering-os"
SOURCE_SHA = "1111111111111111111111111111111111111111"
TARGET_SHA = "2222222222222222222222222222222222222222"
SOURCE_TREE = "3333333333333333333333333333333333333333"
SNAPSHOT_SHA = "4444444444444444444444444444444444444444"
OTHER_SHA = "5555555555555555555555555555555555555555"


class FakeTransport:
    def __init__(
        self,
        *,
        source_sha=SOURCE_SHA,
        target_sha=TARGET_SHA,
        behind=0,
        protected=True,
        existing_branch=None,
        existing_pr=None,
    ):
        self.source_sha = source_sha
        self.target_sha = target_sha
        self.behind = behind
        self.protected = protected
        self.existing_branch = existing_branch
        self.existing_pr = existing_pr
        self.created_branch = False
        self.created_ref_sha = None
        self.created_commit = False
        self.updated_ref = False
        self.created_pr = False
        self.target_reads = 0
        self.create_commit_payload = None
        self.update_ref_payload = None

    def __call__(self, method, url, headers, payload):  # noqa: ANN001
        path = url.removeprefix("https://api.github.com")
        if method == "GET" and path == f"/repos/{REPOSITORY}/branches/ai%2Fintegration":
            return 200, {
                "name": "ai/integration",
                "protected": self.protected,
                "commit": {"sha": self.source_sha},
            }
        if method == "GET" and path == f"/repos/{REPOSITORY}/branches/develop":
            return 200, {
                "name": "develop",
                "protected": self.protected,
                "commit": {"sha": self.target_sha},
            }

        if method == "GET" and path == f"/repos/{REPOSITORY}/commits/ai%2Fintegration":
            return 200, {
                "sha": self.source_sha,
                "commit": {"tree": {"sha": SOURCE_TREE}},
                "parents": [{"sha": OTHER_SHA}],
            }
        if method == "GET" and path == f"/repos/{REPOSITORY}/commits/develop":
            self.target_reads += 1
            return 200, {
                "sha": self.target_sha,
                "commit": {"tree": {"sha": OTHER_SHA}},
                "parents": [],
            }
        if method == "GET" and path == f"/repos/{REPOSITORY}/commits/{SNAPSHOT_SHA}":
            return 200, {
                "sha": SNAPSHOT_SHA,
                "commit": {"tree": {"sha": SOURCE_TREE}},
                "parents": [
                    {"sha": self.target_sha},
                    {"sha": self.source_sha},
                ],
            }

        if method == "GET" and path == f"/repos/{REPOSITORY}/commits/{OTHER_SHA}":
            return 200, {
                "sha": OTHER_SHA,
                "commit": {"tree": {"sha": OTHER_SHA}},
                "parents": [],
            }
        if method == "GET" and path == f"/repos/{REPOSITORY}/git/ref/heads/ai%2F1-develop-promotion":
            if self.existing_branch is None and not self.created_branch:
                return 404, {}
            return 200, {"object": {"sha": self.existing_branch or SNAPSHOT_SHA}}

        if method == "POST" and path == f"/repos/{REPOSITORY}/git/refs":
            self.created_branch = True
            self.created_ref_sha = payload["sha"]
            return 201, {"ref": "refs/heads/ai/1-develop-promotion"}
        if method == "POST" and path == f"/repos/{REPOSITORY}/git/commits":
            self.created_commit = True
            self.create_commit_payload = payload
            return 201, {"sha": SNAPSHOT_SHA}
        if method == "PATCH" and path == f"/repos/{REPOSITORY}/git/refs/heads/ai%2F1-develop-promotion":
            self.updated_ref = True
            self.update_ref_payload = payload
            return 200, {"ref": "refs/heads/ai/1-develop-promotion"}

        if method == "GET" and path.startswith(f"/repos/{REPOSITORY}/pulls?"):
            query = parse_qs(urlparse(path).query)
            self.assert_query = query
            if self.existing_pr is None:
                return 200, []
            return 200, [self.existing_pr]
        if method == "POST" and path == f"/repos/{REPOSITORY}/pulls":
            self.created_pr = True
            return 201, self.pull_request_payload()

        if method == "GET" and path == f"/repos/{REPOSITORY}/compare/{self.target_sha}...{self.source_sha}":
            return 200, {
                "status": "ahead" if self.behind == 0 else "diverged",
                "ahead_by": 2,
                "behind_by": self.behind,
                "total_commits": 2,
                "files": [{"filename": "one.txt"}],
            }

        if method == "GET" and path.startswith(
            f"/repos/{REPOSITORY}/actions/workflows/.github%2Fworkflows%2Fvalidate.yml/runs?"
        ):
            return 200, {
                "workflow_runs": [
                    {
                        "id": 100,
                        "name": "Aegis Validation",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": self.source_sha,
                        "html_url": "https://github.com/KenlikDev/aegis-engineering-os/actions/runs/100",
                    }
                ]
            }

        raise AssertionError(f"Unexpected request: {method} {path}")

    @staticmethod
    def pull_request_payload():
        return {
            "number": 10,
            "html_url": "https://github.com/KenlikDev/aegis-engineering-os/pull/10",
            "state": "open",
            "merged": False,
            "head": {"ref": "ai/1-develop-promotion"},
            "base": {"ref": "develop"},
            "draft": True,
        }


class PromotionSnapshotTests(unittest.TestCase):
    def _request(self, target="develop"):
        return PromotionSnapshotRequest(
            repository=REPOSITORY,
            work_item_id="1",
            target_branch=target,
        )

    def _provider(self, transport):
        return GitHubPromotionSnapshotProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

    def test_creates_snapshot_and_pr(self):
        transport = FakeTransport()
        result = prepare_promotion_snapshot(self._provider(transport), self._request())

        self.assertEqual(SOURCE_SHA, result.source_sha)
        self.assertEqual(TARGET_SHA, result.target_sha)
        self.assertEqual("ai/1-develop-promotion", result.promotion_branch)
        self.assertEqual(SNAPSHOT_SHA, result.promotion_sha)
        self.assertFalse(result.branch_reused)
        self.assertFalse(result.pull_request_reused)
        self.assertTrue(transport.created_branch)
        self.assertEqual(SNAPSHOT_SHA, transport.created_ref_sha)
        self.assertTrue(transport.created_commit)
        self.assertTrue(transport.created_pr)
        self.assertEqual(
            [TARGET_SHA, SOURCE_SHA],
            transport.create_commit_payload["parents"],
        )
        self.assertEqual(SOURCE_TREE, transport.create_commit_payload["tree"])
        self.assertEqual(["KenlikDev:ai/1-develop-promotion"], transport.assert_query["head"])
        self.assertEqual(["develop"], transport.assert_query["base"])

    def test_does_not_publish_incomplete_branch_when_snapshot_commit_fails(self):
        transport = FakeTransport()

        def failing_commit(method, url, headers, payload):  # noqa: ANN001
            if method == "POST" and url.endswith("/git/commits"):
                raise PromotionSnapshotError("snapshot commit failed")
            return transport(method, url, headers, payload)

        provider = GitHubPromotionSnapshotProvider(
            REPOSITORY,
            "secret-token",
            transport=failing_commit,
        )

        with self.assertRaisesRegex(PromotionSnapshotError, "snapshot commit failed"):
            prepare_promotion_snapshot(provider, self._request())

        self.assertFalse(transport.created_branch)

    def test_reuses_matching_snapshot_and_pr(self):
        transport = FakeTransport(
            existing_branch=SNAPSHOT_SHA,
            existing_pr=FakeTransport.pull_request_payload(),
        )
        result = prepare_promotion_snapshot(self._provider(transport), self._request())

        self.assertTrue(result.branch_reused)
        self.assertTrue(result.pull_request_reused)
        self.assertEqual(SNAPSHOT_SHA, result.promotion_sha)
        self.assertFalse(transport.created_branch)
        self.assertFalse(transport.created_commit)
        self.assertFalse(transport.updated_ref)
        self.assertFalse(transport.created_pr)

    def test_blocks_when_target_is_behind(self):
        transport = FakeTransport(behind=1)
        with self.assertRaisesRegex(
            PromotionSnapshotError,
            "ai/integration is behind develop by 1 commit",
        ):
            prepare_promotion_snapshot(self._provider(transport), self._request())

        self.assertFalse(transport.created_branch)
        self.assertFalse(transport.created_commit)
        self.assertFalse(transport.created_pr)

    def test_blocks_unprotected_target(self):
        transport = FakeTransport(protected=False)
        with self.assertRaisesRegex(
            PromotionSnapshotError,
            "must remain protected",
        ):
            prepare_promotion_snapshot(self._provider(transport), self._request())
        self.assertFalse(transport.created_branch)

    def test_rejects_mismatched_existing_branch(self):
        transport = FakeTransport(existing_branch=OTHER_SHA)
        with self.assertRaisesRegex(
            PromotionSnapshotError,
            "does not match the current snapshot",
        ):
            prepare_promotion_snapshot(self._provider(transport), self._request())
        self.assertFalse(transport.created_commit)

    def test_rejects_invalid_target_before_network_access(self):
        transport = FakeTransport()
        request = self._request(target="release")
        with self.assertRaisesRegex(
            PromotionSnapshotError,
            "target must be develop or main",
        ):
            prepare_promotion_snapshot(self._provider(transport), request)
        self.assertFalse(transport.created_branch)
        self.assertFalse(transport.created_pr)

    def test_blocks_target_change_after_snapshot_verification(self):
        transport = FakeTransport()
        calls = {"target_reads": 0}

        def changing_call(method, url, headers, payload):  # noqa: ANN001
            if method == "GET" and url.endswith("/commits/develop"):
                calls["target_reads"] += 1
                if calls["target_reads"] >= 2:
                    return 200, {
                        "sha": OTHER_SHA,
                        "commit": {"tree": {"sha": OTHER_SHA}},
                        "parents": [],
                    }
            return transport(method, url, headers, payload)

        provider = GitHubPromotionSnapshotProvider(
            REPOSITORY,
            "secret-token",
            transport=changing_call,
        )
        with self.assertRaisesRegex(
            PromotionSnapshotError,
            "changed while the promotion snapshot",
        ):
            prepare_promotion_snapshot(provider, self._request())
        self.assertFalse(transport.created_pr)


if __name__ == "__main__":
    unittest.main()
