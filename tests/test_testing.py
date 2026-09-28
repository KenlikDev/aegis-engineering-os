import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from testing import TestingWorkflowError, prepare_testing, run_testing
from work_item_lifecycle import InMemoryWorkItemProvider, LifecycleState, WorkItem


MANIFEST = """{
  "schema_version": 1,
  "gates": [
    {
      "id": "unit-tests",
      "description": "Run unit tests",
      "command": ["python", "-c", "print('ok')"],
      "required": true
    },
    {
      "id": "lint",
      "description": "Run lint",
      "command": ["python", "-c", "print('optional')"],
      "required": false
    }
  ]
}
"""


class TestingWorkflowTests(unittest.TestCase):
    def _project(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / ".aegis").mkdir()
        (root / ".aegis" / "quality-gates.json").write_text(MANIFEST, encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return root

    def test_prepare_requires_explicit_manifest_inside_project(self):
        root = self._project()
        plan = prepare_testing(root)
        self.assertEqual(("unit-tests",), plan.required_gate_ids)
        self.assertEqual(2, len(plan.gates))

        with self.assertRaises(TestingWorkflowError):
            prepare_testing(root, Path(tempfile.gettempdir()) / "quality-gates.json")

    def test_provider_requires_verification_state(self):
        root = self._project()
        provider = InMemoryWorkItemProvider(
            {
                "98": WorkItem(
                    id="98",
                    title="testing",
                    state=LifecycleState.READY,
                    provider="memory",
                )
            }
        )

        with self.assertRaisesRegex(TestingWorkflowError, "verification state"):
            prepare_testing(root, work_item_provider=provider, work_item_id="98")

        provider.transition("98", LifecycleState.IN_PROGRESS)
        with self.assertRaisesRegex(TestingWorkflowError, "verification state"):
            prepare_testing(root, work_item_provider=provider, work_item_id="98")

        provider.transition("98", LifecycleState.VERIFICATION)
        plan = prepare_testing(root, work_item_provider=provider, work_item_id="98")
        self.assertEqual("verification", plan.lifecycle_state)

    def test_execution_delegates_to_quality_gate_contract(self):
        root = self._project()

        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "passed\n", "")

        evidence = run_testing(root, run_command=fake_runner)

        self.assertEqual("verified", evidence["status"])
        self.assertEqual([], evidence["required_failures"])
        self.assertEqual(["unit-tests"], evidence["testing_contract"]["required_gate_ids"])

    def test_standalone_execution_persists_evidence(self):
        root = self._project()
        evidence_path = root / "artifacts" / "testing.json"

        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "passed\\n", "")

        evidence = run_testing(
            root,
            evidence_path=evidence_path,
            run_command=fake_runner,
        )

        self.assertEqual("verified", evidence["status"])
        self.assertTrue(evidence_path.is_file())
        self.assertEqual("verified", json.loads(evidence_path.read_text(encoding="utf-8"))["status"])

    def test_required_failure_is_not_bypassed(self):
        root = self._project()

        def fake_runner(command, **kwargs):
            if command[0] == "python":
                return subprocess.CompletedProcess(command, 1, "", "failed")
            return subprocess.CompletedProcess(command, 0, "", "")

        evidence = run_testing(root, run_command=fake_runner)

        self.assertEqual("failed", evidence["status"])
        self.assertEqual(["unit-tests"], evidence["required_failures"])

    def test_work_item_synchronization_uses_existing_quality_gate_contract(self):
        root = self._project()
        provider = InMemoryWorkItemProvider(
            {
                "98": WorkItem(
                    id="98",
                    title="testing",
                    state=LifecycleState.VERIFICATION,
                    provider="memory",
                )
            }
        )

        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "passed\n", "")

        evidence = run_testing(
            root,
            work_item_provider=provider,
            work_item_id="98",
            run_command=fake_runner,
        )

        self.assertEqual("verified", evidence["status"])
        self.assertEqual(
            LifecycleState.REVIEW,
            provider.get("98").state,
        )


if __name__ == "__main__":
    unittest.main()
