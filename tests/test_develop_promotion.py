import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from develop_promotion import (  # noqa: E402
    DevelopPromotionError,
    DevelopPromotionRequest,
    GitHubDevelopPromotionProvider,
    prepare_develop_promotion,
)
from promotion_readiness import PromotionReadiness
from work_item_lifecycle import LifecycleState, WorkItem

REPOSITORY = "KenlikDev/aegis-engineering-os"
SOURCE_SHA = "1111111111111111111111111111111111111111"
TARGET_SHA = "2222222222222222222222222222222222222222"
OTHER_SHA = "3333333333333333333333333333333333333333"


class FakeTransport:
    def __init__(
        self,
        *,
        source_sha=SOURCE_SHA,
        target_sha=TARGET_SHA,
        protected=True,
        existing_pr=None,
        validation=True,
    ):
        self.source_sha = source_sha
        self.target_sha = target_sha
        self.protected = protected
        self.existing_pr = existing_pr
        self.validation = validation
        self.created_pr = False
        self.created_payload = None

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
        if method == "GET" and path.startswith(
            f"/repos/{REPOSITORY}/actions/workflows/.github%2Fworkflows%2Fvalidate.yml/runs?"
        ):
            runs = (
                [
                    {
                        "id": 100,
                        "name": "Aegis Validation",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": self.source_sha,
                        "html_url": "https://github.com/KenlikDev/aegis-engineering-os/actions/runs/100",
                    }
                ]
                if self.validation
                else []
            )
            return 200, {"workflow_runs": runs}
        if method == "GET" and path.startswith(f"/repos/{REPOSITORY}/pulls?"):
            return 200, [self.existing_pr] if self.existing_pr is not None else []
        if method == "POST" and path == f"/repos/{REPOSITORY}/pulls":
            self.created_pr = True
            self.created_payload = payload
            return 201, self.pull_request_payload()
        if method == "GET" and path == f"/repos/{REPOSITORY}/pulls/10":
            if self.existing_pr is not None:
                return 200, self.existing_pr
            return 200, self.pull_request_payload()
        if method == "GET" and "/compare/" in path:
            return 200, {
                "status": "ahead",
                "ahead_by": 2,
                "behind_by": 0,
                "total_commits": 2,
                "files": [{"filename": "one.txt"}],
            }
        raise AssertionError(f"Unexpected request: {method} {path}")

    def pull_request_payload(self, *, head_sha=None, body=None):
        head_sha = head_sha or self.source_sha
        body = body or (
            "## Aegis owner-gated develop promotion\n\n"
            f"- Verified source SHA: {self.source_sha}\n"
        )
        return {
            "number": 10,
            "html_url": "https://github.com/KenlikDev/aegis-engineering-os/pull/10",
            "state": "open",
            "merged_at": None,
            "body": body,
            "head": {
                "ref": "ai/integration",
                "sha": head_sha,
                "repo": {"full_name": REPOSITORY},
            },
            "base": {
                "ref": "develop",
                "sha": TARGET_SHA,
                "repo": {"full_name": REPOSITORY},
            },
            "draft": True,
        }


class FakeWorkItemProvider:
    def __init__(self, state=LifecycleState.INTEGRATION):
        self.item = WorkItem(
            id="324",
            title="Develop promotion task",
            state=state,
            provider="fake",
            provider_url="https://example.test/issues/324",
        )

    def get(self, work_item_id):
        if work_item_id != "324":
            raise AssertionError(f"Unexpected work item: {work_item_id}")
        return self.item


class LifecycleRecheckingWorkItemProvider(FakeWorkItemProvider):
    def __init__(self, second_state=LifecycleState.REVIEW):
        super().__init__(LifecycleState.INTEGRATION)
        self.second_state = second_state
        self.get_calls = 0

    def get(self, work_item_id):
        item = super().get(work_item_id)
        self.get_calls += 1
        if self.get_calls >= 2:
            return WorkItem(
                id=item.id,
                title=item.title,
                state=self.second_state,
                provider=item.provider,
                provider_url=item.provider_url,
            )
        return item


class RecheckingProvider(GitHubDevelopPromotionProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.readiness_calls = 0

    def assess_readiness(self, **kwargs):
        self.readiness_calls += 1
        result = super().assess_readiness(**kwargs)
        if self.readiness_calls == 2:
            return PromotionReadiness(
                repository=result.repository,
                source=result.source,
                target=result.target,
                compare=result.compare,
                validation=result.validation,
                blockers=("ai/integration changed after owner verification.",),
            )
        return result


class DevelopPromotionTests(unittest.TestCase):
    def _request(self, sha=SOURCE_SHA, target="develop"):
        return DevelopPromotionRequest(
            repository=REPOSITORY,
            work_item_id="324",
            owner_verified_source_sha=sha,
            target_branch=target,
        )

    def _work_item_provider(self, state=LifecycleState.INTEGRATION):
        return FakeWorkItemProvider(state)

    def _provider(self, transport):
        return GitHubDevelopPromotionProvider(
            REPOSITORY,
            "test-token",
            transport=transport,
        )

    def test_creates_direct_develop_pr_from_owner_verified_sha(self):
        transport = FakeTransport()
        result = prepare_develop_promotion(
            self._provider(transport),
            self._work_item_provider(),
            self._request(),
        )

        self.assertEqual(SOURCE_SHA, result.source_sha)
        self.assertEqual(TARGET_SHA, result.target_sha)
        self.assertEqual("ai/integration", result.pull_request.head)
        self.assertEqual(SOURCE_SHA, result.pull_request.head_sha)
        self.assertEqual("develop", result.pull_request.base)
        self.assertEqual(TARGET_SHA, result.pull_request.base_sha)
        self.assertEqual(SOURCE_SHA, result.validation["validated_sha"])
        self.assertTrue(transport.created_pr)
        self.assertEqual("ai/integration", transport.created_payload["head"])
        self.assertEqual("develop", transport.created_payload["base"])
        self.assertIn(
            f"- Verified source SHA: {SOURCE_SHA}",
            transport.created_payload["body"],
        )

    def test_recheck_rejects_work_item_lifecycle_drift_before_pr_write(self):
        transport = FakeTransport()
        work_item_provider = LifecycleRecheckingWorkItemProvider()
        with self.assertRaisesRegex(
            DevelopPromotionError,
            "requires the work item to be in integration state",
        ):
            prepare_develop_promotion(
                self._provider(transport),
                work_item_provider,
                self._request(),
            )
        self.assertEqual(2, work_item_provider.get_calls)
        self.assertFalse(transport.created_pr)

    def test_recheck_rejects_stale_source_before_pr_write(self):
        transport = FakeTransport()
        provider = RecheckingProvider(
            REPOSITORY,
            "test-token",
            transport=transport,
        )
        with self.assertRaisesRegex(
            DevelopPromotionError,
            "Promotion readiness is blocked before develop PR write",
        ):
            prepare_develop_promotion(
                provider,
                self._work_item_provider(),
                self._request(),
            )
        self.assertEqual(2, provider.readiness_calls)
        self.assertFalse(transport.created_pr)

    def test_rejects_stale_owner_verified_sha_before_pr_write(self):
        transport = FakeTransport(source_sha=OTHER_SHA)
        with self.assertRaisesRegex(
            DevelopPromotionError,
            "Promotion readiness is blocked",
        ):
            prepare_develop_promotion(
            self._provider(transport),
            self._work_item_provider(),
            self._request(),
        )
        self.assertFalse(transport.created_pr)

    def test_rejects_unprotected_target(self):
        transport = FakeTransport(protected=False)
        with self.assertRaisesRegex(DevelopPromotionError, "must remain protected"):
            prepare_develop_promotion(
            self._provider(transport),
            self._work_item_provider(),
            self._request(),
        )
        self.assertFalse(transport.created_pr)

    def test_reuses_matching_open_direct_pr(self):
        transport = FakeTransport(
            existing_pr={
                "number": 10,
                "html_url": "https://github.com/KenlikDev/aegis-engineering-os/pull/10",
                "state": "open",
                "merged_at": None,
                "body": (
                    "## Aegis owner-gated develop promotion\n\n"
                    f"- Verified source SHA: {SOURCE_SHA}\n"
                ),
                "head": {
                    "ref": "ai/integration",
                    "sha": SOURCE_SHA,
                    "repo": {"full_name": REPOSITORY},
                },
                "base": {
                    "ref": "develop",
                    "sha": TARGET_SHA,
                    "repo": {"full_name": REPOSITORY},
                },
                "draft": True,
            }
        )
        result = prepare_develop_promotion(
            self._provider(transport),
            self._work_item_provider(),
            self._request(),
        )
        self.assertTrue(result.pull_request_reused)
        self.assertFalse(transport.created_pr)

    def test_rejects_fork_origin(self):
        transport = FakeTransport()
        original_payload = transport.pull_request_payload

        def fork_payload(**kwargs):
            payload = original_payload(**kwargs)
            payload["head"]["repo"]["full_name"] = "KenlikDev/forked-aegis"
            return payload

        transport.pull_request_payload = fork_payload
        with self.assertRaisesRegex(
            DevelopPromotionError,
            "verification failed",
        ):
            prepare_develop_promotion(
                self._provider(transport),
                self._work_item_provider(),
                self._request(),
            )
        self.assertTrue(transport.created_pr)

    def test_cli_can_write_canonical_evidence(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import develop_promotion as module
        from evidence_contract import read_and_validate_evidence

        transport = FakeTransport()
        provider = self._provider(transport)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "develop-promotion.json"
            argv = [
                "develop_promotion.py",
                REPOSITORY,
                "324",
                "--owner-verified-source-sha",
                SOURCE_SHA,
                "--evidence-output",
                str(output),
            ]
            with (
                patch.object(module, "GitHubDevelopPromotionProvider", return_value=provider),
                patch.object(module, "GitHubIssuesProvider", return_value=self._work_item_provider()),
                patch.object(sys, "argv", argv),
            ):
                self.assertEqual(0, module.main())

            evidence = read_and_validate_evidence(output)
            self.assertEqual("develop-promotion", evidence.kind)
            self.assertEqual(SOURCE_SHA, evidence.revision)
            self.assertEqual(REPOSITORY, evidence.result["pull_request"]["head_repository"])

    def test_rejects_non_develop_target(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(DevelopPromotionError, "target must be develop"):
            prepare_develop_promotion(
                self._provider(transport),
                self._work_item_provider(),
                self._request(target="main"),
            )

    def test_rejects_non_integrated_work_item_before_pr_write(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(
            DevelopPromotionError,
            "requires the work item to be in integration state",
        ):
            prepare_develop_promotion(
                self._provider(transport),
                self._work_item_provider(LifecycleState.REVIEW),
                self._request(),
            )
        self.assertFalse(transport.created_pr)

    def test_rejects_malformed_verified_sha(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(
            DevelopPromotionError,
            "Owner-verified source SHA is malformed",
        ):
            prepare_develop_promotion(
                self._provider(transport),
                self._work_item_provider(),
                self._request(sha="not-a-sha"),
            )


if __name__ == "__main__":
    unittest.main()
