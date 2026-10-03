#!/usr/bin/env python3
"""Tests for the managed Aegis execution workflow contract."""

import unittest
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "aegis-managed-execution.yml"
)


class AegisManagedExecutionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_is_manual_dispatch_only(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("push:", self.workflow)
        self.assertNotIn("pull_request:", self.workflow)

    def test_operation_is_explicitly_allowlisted(self):
        self.assertIn("- transition", self.workflow)
        self.assertIn("- integrate", self.workflow)

    def test_execution_is_restricted_to_integration_branch(self):
        self.assertIn("github.ref == 'refs/heads/ai/integration'", self.workflow)

    def test_expected_state_is_required(self):
        self.assertIn("expected_state:", self.workflow)
        block = self.workflow.split("expected_state:", 1)[1].split("target_state:", 1)[0]
        self.assertIn("required: true", block)

    def test_transition_delegates_to_canonical_lifecycle_tool(self):
        self.assertIn(
            'python tools/work_item_lifecycle.py transition '
            '"$REPOSITORY" "$WORK_ITEM_ID" "$TARGET_STATE" '
            '--expected-state "$EXPECTED_STATE"',
            self.workflow,
        )

    def test_integration_delegates_to_canonical_delivery_tool(self):
        self.assertIn(
            'python tools/integration_delivery.py "$REPOSITORY" "$WORK_ITEM_ID" "$HEAD_BRANCH" "$PR_TITLE"',
            self.workflow,
        )
        self.assertIn("--canonical-evidence-output", self.workflow)
        self.assertIn('test "$EXPECTED_STATE" = "review"', self.workflow)

    def test_permissions_are_scoped_to_required_apis(self):
        expected = [
            "contents: write",
            "issues: write",
            "pull-requests: write",
            "actions: read",
            "checks: read",
        ]
        for permission in expected:
            self.assertIn(permission, self.workflow)

    def test_no_arbitrary_shell_input_is_executed(self):
        self.assertNotIn("eval ", self.workflow)
        self.assertNotIn("bash -c", self.workflow)
        self.assertNotIn("sh -c", self.workflow)


if __name__ == "__main__":
    unittest.main()
