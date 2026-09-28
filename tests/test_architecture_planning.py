import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from architecture_planning import ArchitecturePlanningError, plan_architecture
from work_item_lifecycle import LifecycleState


VALID = """# Work Item

## Identity

Provider: GitHub Issues
Work item ID: 96
Title: Add architecture planning

## Intent

Produce a deterministic architecture plan before implementation.

## Scope

### In scope

- Add the architecture planning workflow.

### Out of scope

- Change project source code automatically.

## Acceptance criteria

- [ ] The plan separates evidence from deductions.
- [ ] Missing architecture evidence blocks readiness.

## Dependencies

- tools/requirements_clarification.py.

## Roles

Primary role:

Software Architect

## Technical notes

Affected component: planning workflow
Module: tools/architecture_planning.py
Keep the workflow read-only and deterministic.

## Risks

- Ambiguous architecture ownership must not become an invented decision.

## Verification plan

- Run the architecture planning regression tests.
"""

NO_ARCHITECTURE_EVIDENCE = VALID.replace(
    "Affected component: planning workflow\nModule: tools/architecture_planning.py\nKeep the workflow read-only and deterministic.",
    "",
)

INCOMPLETE_REQUIREMENTS = VALID.replace(
    "Title: Add architecture planning",
    "Title:",
)


@dataclass(frozen=True)
class FakeWorkItem:
    state: LifecycleState


class FakeReader:
    def __init__(self, state: LifecycleState):
        self.state = state
        self.calls = []

    def get(self, work_item_id: str):
        self.calls.append(work_item_id)
        return FakeWorkItem(self.state)


class ArchitecturePlanningTests(unittest.TestCase):
    def _write(self, source: str):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "work-item.md"
        path.write_text(source, encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return path

    def test_ready_plan_preserves_evidence_and_deductions(self):
        path = self._write(VALID)
        before = path.read_bytes()

        plan = plan_architecture(path)

        self.assertTrue(plan.ready)
        self.assertEqual("ready", plan.status)
        self.assertEqual("ready", plan.requirements_status)
        self.assertIn("planning workflow", plan.affected_components)
        self.assertTrue(plan.evidence)
        self.assertTrue(plan.deductions)
        self.assertEqual(before, path.read_bytes())

    def test_missing_architecture_evidence_blocks(self):
        path = self._write(NO_ARCHITECTURE_EVIDENCE)

        plan = plan_architecture(path)

        self.assertFalse(plan.ready)
        blocker_ids = {item.question_id for item in plan.blockers}
        self.assertIn("architecture.technical-notes", blocker_ids)
        self.assertIn("architecture.affected-components", blocker_ids)

    def test_requirements_blocker_is_preserved_as_user_owned_question(self):
        path = self._write(INCOMPLETE_REQUIREMENTS)

        plan = plan_architecture(path)

        self.assertFalse(plan.ready)
        question_ids = {item.question_id for item in plan.user_owned_decisions}
        self.assertIn("identity.title", question_ids)

    def test_lifecycle_must_be_ready_when_provider_is_supplied(self):
        path = self._write(VALID)
        reader = FakeReader(LifecycleState.PLANNED)

        with self.assertRaisesRegex(ArchitecturePlanningError, "requires a ready work item"):
            plan_architecture(path, work_item_reader=reader, work_item_id="96")

        self.assertEqual(["96"], reader.calls)

    def test_ready_lifecycle_state_is_recorded(self):
        path = self._write(VALID)
        reader = FakeReader(LifecycleState.READY)

        plan = plan_architecture(path, work_item_reader=reader, work_item_id="96")

        self.assertTrue(plan.ready)
        self.assertEqual("96", plan.work_item_id)
        self.assertEqual("ready", plan.lifecycle_state)

    def test_lifecycle_arguments_must_be_complete(self):
        path = self._write(VALID)

        with self.assertRaisesRegex(ArchitecturePlanningError, "must be provided together"):
            plan_architecture(path, work_item_id="96")

    def test_plan_is_deterministic(self):
        path = self._write(VALID)

        first = plan_architecture(path)
        second = plan_architecture(path)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
