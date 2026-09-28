import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from workflow_composition import WorkflowCompositionError, compose_workflow


class WorkflowCompositionTests(unittest.TestCase):
    def test_kind_is_explicit_and_supported(self):
        with self.assertRaisesRegex(WorkflowCompositionError, "does not infer a kind"):
            compose_workflow("Fix an authentication bug")

        composition = compose_workflow("refactoring")
        self.assertEqual("refactoring", composition.work_item_kind)

    def test_registry_references_are_validated(self):
        composition = compose_workflow("feature")
        names = {step.name for step in composition.steps}
        self.assertIn("feature-implementation", names)
        self.assertIn("testing", names)
        self.assertIn("code-review", names)

    def test_conditional_steps_remain_explicit(self):
        composition = compose_workflow("refactoring")
        architecture = next(
            step for step in composition.steps if step.name == "architecture-planning"
        )
        self.assertFalse(architecture.required)
        self.assertIsNotNone(architecture.condition)

    def test_compositions_are_deterministic(self):
        first = compose_workflow("bug-fix")
        second = compose_workflow("bug-fix")
        self.assertEqual(first, second)

    def test_unknown_registry_capability_fails_closed(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "registry.json"
        path.write_text(
            json.dumps({"skills": [{"name": "work-item-lifecycle"}]}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(WorkflowCompositionError, "unregistered skills"):
            compose_workflow("feature", registry_path=path)

    def test_common_sequence_verifies_versions_before_architecture(self):
        steps = compose_workflow("feature").steps
        names = [step.name for step in steps]
        self.assertEqual(
            ["work-item-lifecycle", "requirements-clarification", "project-discovery",
             "version-verification", "architecture-planning"],
            names[:5],
        )
        version_step = steps[3]
        self.assertEqual("skill", version_step.kind)

    def test_each_supported_kind_has_expected_primary_workflow(self):
        expected = {
            "feature": "feature-implementation",
            "bug-fix": "bug-fix",
            "refactoring": "refactoring",
            "ci-remediation": "ci-remediation",
        }
        for kind, primary in expected.items():
            with self.subTest(kind=kind):
                names = {step.name for step in compose_workflow(kind).steps}
                self.assertIn(primary, names)


if __name__ == "__main__":
    unittest.main()
