import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"


class ChangelogOrderingTests(unittest.TestCase):
    def test_unreleased_contains_all_current_implementation_entries(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        unreleased = text.split("## Unreleased", 1)[1].split(
            "## 0.1.0-alpha.1", 1
        )[0]
        historical = text.split("## 0.1.0-alpha.1", 1)[1]

        self.assertIn(
            "harden promotion readiness to accept verified merged-pull-request CI evidence",
            unreleased,
        )
        self.assertIn(
            "add the executable knowledge-gap candidate registry",
            unreleased,
        )
        self.assertIn(
            "add a composed integration delivery controller",
            unreleased,
        )

        self.assertNotIn(
            "harden promotion readiness to accept verified merged-pull-request CI evidence",
            historical,
        )
        self.assertNotIn(
            "add the executable knowledge-gap candidate registry",
            historical,
        )

    def test_historical_initial_release_has_no_unreleased_entries(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        historical = text.split("## 0.1.0-alpha.1", 1)[1]
        self.assertIn("- constitution and agent operating rules;", historical)
        self.assertNotIn("- add the controlled ai/integration merge boundary", historical)
        self.assertNotIn("- add promotion merge synchronization", historical)

    def test_every_bullet_occurs_only_once(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        bullets = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("- ")
        ]
        self.assertEqual(len(bullets), len(set(bullets)))

    def test_no_release_bullets_appear_before_unreleased_heading(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        header = text.split("## Unreleased", 1)[0]
        self.assertNotIn("\n- ", header)


if __name__ == "__main__":
    unittest.main()
