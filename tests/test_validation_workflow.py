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

    def test_checks_out_actual_merge_commit_for_closed_merged_pr(self):
        self.assertIn(
            "github.event.pull_request.merge_commit_sha || github.sha",
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
