import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "03-workflows" / "README.md"


CORE_WORKFLOW_DISPLAY_NAMES = {
    "project-discovery": "project discovery",
    "work-item-lifecycle": "work-item lifecycle",
    "feature-implementation": "feature implementation",
    "bug-fix": "bug fixing",
    "code-review": "code review",
    "aegis-update-validation": "Aegis update validation",
    "release-preparation": "release preparation",
    "promotion-synchronization": "promotion synchronization",
    "integration-merge": "integration merge",
    "integration-delivery": "integration delivery",
    "security-review": "security review",
    "ci-remediation": "ci remediation",
    "requirements-clarification": "requirements clarification",
    "architecture-planning": "architecture planning",
    "testing": "testing",
    "refactoring": "refactoring",
}


class WorkflowCatalogTests(unittest.TestCase):
    def test_every_core_workflow_is_listed_as_implemented(self):
        catalog = CATALOG.read_text(encoding="utf-8")
        match = re.search(
            r"## Implemented workflows\s+(.*?)\s+## Planned workflow areas",
            catalog,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        implemented = match.group(1)

        for skill_name, display_name in CORE_WORKFLOW_DISPLAY_NAMES.items():
            with self.subTest(skill=skill_name):
                if display_name == "release preparation":
                    self.assertIn(
                        "- release preparation and release readiness;",
                        implemented,
                    )
                elif display_name == "integration delivery":
                    self.assertIn("- integration delivery;", implemented)
                elif display_name == "architecture planning":
                    self.assertIn("- architecture planning;", implemented)
                elif display_name == "testing":
                    self.assertIn("- testing;", implemented)
                elif display_name == "refactoring":
                    self.assertIn("- refactoring;", implemented)
                else:
                    self.assertIn(f"- {display_name};", implemented)

    def test_catalog_keeps_planned_and_implemented_sections_distinct(self):
        catalog = CATALOG.read_text(encoding="utf-8")
        implemented = catalog.split("## Implemented workflows", 1)[1].split(
            "## Planned workflow areas", 1
        )[0]
        planned = catalog.split("## Planned workflow areas", 1)[1]

        self.assertIn("- integration delivery;", implemented)
        self.assertNotIn("- integration delivery.", planned)
        self.assertNotIn("- ci remediation;", planned)
        self.assertNotIn("- requirements clarification;", planned)
        self.assertNotIn("- architecture planning;", planned)
        self.assertNotRegex(planned, r"(?m)^- testing(?:[.;]|$)")
        self.assertNotRegex(planned, r"(?m)^- refactoring(?:[.;]|$)")


if __name__ == "__main__":
    unittest.main()
