import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "workflows" / "refactoring" / "SKILL.md"
ARCHITECTURE = ROOT / "docs" / "architecture" / "refactoring.md"
CATALOG = ROOT / "03-workflows" / "README.md"
REGISTRY = ROOT / "skills" / "registry.json"
LIFECYCLE = ROOT / "skills" / "workflows" / "work-item-lifecycle" / "SKILL.md"
README = ROOT / "README.md"


class RefactoringWorkflowContractTests(unittest.TestCase):
    def test_canonical_contract_exists_and_is_english(self):
        for path in (SKILL, ARCHITECTURE):
            content = path.read_text(encoding="utf-8")
            self.assertNotRegex(content, r"[А-Яа-яЁё]")

    def test_skill_requires_baseline_and_post_change_testing(self):
        content = SKILL.read_text(encoding="utf-8")
        self.assertIn("Establish a verified baseline", content)
        self.assertIn("Re-run focused and broader declared quality gates", content)
        self.assertIn("Record any discovered behavior change as scope change", content)

    def test_architecture_preserves_composed_boundaries(self):
        content = ARCHITECTURE.read_text(encoding="utf-8")
        self.assertIn("requirements clarification", content)
        self.assertIn("verified baseline testing", content)
        self.assertIn("post-change testing", content)
        self.assertIn("independent code review", content)
        self.assertIn("The workflow never hides behavior changes inside a refactor.", content)

    def test_registry_catalog_and_lifecycle_are_wired(self):
        registry = REGISTRY.read_text(encoding="utf-8")
        catalog = CATALOG.read_text(encoding="utf-8")
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        readme = README.read_text(encoding="utf-8")

        self.assertIn('"name": "refactoring"', registry)
        self.assertIn("- refactoring;", catalog)
        self.assertNotRegex(
            catalog.split("## Planned workflow areas", 1)[1],
            r"(?m)^- refactoring(?:[.;]|$)",
        )
        self.assertIn("## Refactoring", lifecycle)
        self.assertIn("## Refactoring", readme)


if __name__ == "__main__":
    unittest.main()
