import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"


class ValidationWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_preserves_read_only_permissions(self):
        self.assertIn("permissions:\n  contents: read", self.workflow)

    def test_validates_closed_merged_pull_requests(self):
        self.assertIn("      - closed", self.workflow)
        self.assertIn(
            "github.event.pull_request.merged == true",
            self.workflow,
        )

    def test_checks_out_exact_pull_request_head_for_open_events(self):
        self.assertIn(
            "github.event.pull_request.head.sha ||",
            self.workflow,
        )

    def test_verifies_exact_pull_request_head_checkout(self):
        self.assertIn(
            'test "$(git rev-parse HEAD)" = "${{ github.event.pull_request.head.sha }}"',
            self.workflow,
        )

    def test_checks_out_actual_merge_commit_for_closed_merged_pr(self):
        self.assertIn(
            "github.event.pull_request.merge_commit_sha || github.sha",
            self.workflow,
        )

    def test_separates_push_and_pull_request_concurrency(self):
        self.assertIn(
            "github.event_name",
            self.workflow.split("  group:", 1)[1].split("\n", 1)[0],
        )
        self.assertIn(
            "github.event.pull_request.number || github.ref",
            self.workflow.split("  group:", 1)[1].split("\n", 1)[0],
        )

    def test_isolates_push_runs_by_commit_sha(self):
        group_line = self.workflow.split("  group:", 1)[1].split("\n", 1)[0]
        self.assertIn(
            "github.event_name == 'push' && github.sha",
            group_line,
        )

    def test_does_not_cancel_push_or_merged_close_runs(self):
        self.assertIn(
            "cancel-in-progress: ${{ github.event_name == 'pull_request' && github.event.action != 'closed' }}",
            self.workflow,
        )
        self.assertNotIn("cancel-in-progress: true", self.workflow)
    def test_limits_closed_event_path_to_merged_integration(self):
        self.assertIn(
            "github.event.pull_request.base.ref == 'ai/integration'",
            self.workflow,
        )

    def test_keeps_existing_pr_target_filters(self):
        pull_request_block = self.workflow.split("  pull_request:\n", 1)[1]
        pull_request_block = pull_request_block.split("\n\npermissions:", 1)[0]

        for branch in ("main", "develop", "ai/integration"):
            self.assertIn(f"      - {branch}", pull_request_block)

    def test_does_not_use_pull_request_target(self):
        self.assertNotIn("pull_request_target", self.workflow)


if __name__ == "__main__":
    unittest.main()
