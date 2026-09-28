import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from requirements_clarification import (  # noqa: E402
    RequirementsClarificationError,
    clarify_requirements,
)


VALID = """# Work Item

## Identity

Provider: GitHub Issues

Work item ID: 93

Title: Add deterministic requirements clarification

## Intent

Ensure every non-trivial task has enough observable requirements to begin implementation.

## Scope

### In scope

- Validate the canonical work-item structure.

### Out of scope

- Invent missing business decisions.

## Acceptance criteria

- [ ] Required sections are checked deterministically.
- [ ] Missing requirements produce explicit questions.

## Dependencies

- Existing work-item template.

## Roles

Primary role:

Software Engineer

## Technical notes

Keep the workflow read-only.

## Risks

- Ambiguous requirements may remain.

## Verification plan

- Run the requirements clarification tests.
"""

INVALID = """# Work Item

## Identity

Provider: GitHub Issues
Work item ID:
Title:

## Intent

What outcome is required?

## Scope

### In scope

- ...

### Out of scope

- ...

## Acceptance criteria

- [ ] ...

## Verification plan

- ...
"""


class RequirementsClarificationTests(unittest.TestCase):
    def test_complete_work_item_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "work-item.md"
            path.write_text(VALID, encoding="utf-8")

            before = path.read_text(encoding="utf-8")
            report = clarify_requirements(path)
            after = path.read_text(encoding="utf-8")

            self.assertTrue(report.ready)
            self.assertEqual("ready", report.status)
            self.assertEqual([], list(report.questions))
            self.assertEqual(before, after)

    def test_incomplete_work_item_reports_required_blockers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "work-item.md"
            path.write_text(INVALID, encoding="utf-8")

            report = clarify_requirements(path)

            self.assertFalse(report.ready)
            self.assertEqual("needs-clarification", report.status)
            question_ids = {question.question_id for question in report.questions}
            self.assertIn("identity.title", question_ids)
            self.assertIn("intent.outcome", question_ids)
            self.assertIn("scope.in", question_ids)
            self.assertIn("scope.out", question_ids)
            self.assertIn("acceptance.criteria", question_ids)
            self.assertIn("verification.plan", question_ids)

    def test_missing_optional_context_is_warning_only(self):
        source = VALID.replace(
            """## Dependencies

- Existing work-item template.
""",
            "",
        ).replace(
            """## Risks

- Ambiguous requirements may remain.
""",
            "",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "work-item.md"
            path.write_text(source, encoding="utf-8")

            report = clarify_requirements(path)

            self.assertTrue(report.ready)
            self.assertEqual("ready", report.status)
            self.assertIn(
                "dependencies.unknown",
                {question.question_id for question in report.questions},
            )
            self.assertIn(
                "risks.unknown",
                {question.question_id for question in report.questions},
            )
            self.assertTrue(
                all(question.severity == "warning" for question in report.questions)
            )

    def test_nonexistent_work_item_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.md"
            with self.assertRaisesRegex(
                RequirementsClarificationError,
                "does not exist",
            ):
                clarify_requirements(path)


if __name__ == "__main__":
    unittest.main()
