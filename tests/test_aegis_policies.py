import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AegisPolicyTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_state_verification_skill_exists_and_is_registered(self) -> None:
        skill_path = ROOT / "skills/state-verification/SKILL.md"
        self.assertTrue(skill_path.is_file())

        registry = self.read("skills/registry.json")
        self.assertIn('"name":"state-verification"', registry)
        self.assertIn('"path":"skills/state-verification/SKILL.md"', registry)

    def test_user_claims_are_not_external_state_evidence(self) -> None:
        agents = self.read("AGENTS.md")
        constitution = self.read("00-constitution/core-principles.md")
        skill = self.read("skills/state-verification/SKILL.md")

        required_phrases = (
            "not proof of independently observable state",
            "Verify current state from the strongest available authoritative source",
            "read the resulting state back",
            "Distinguish verified facts, user-provided claims, assumptions",
        )

        for phrase in required_phrases:
            self.assertTrue(
                phrase in agents or phrase in constitution or phrase in skill,
                msg=f"Missing policy phrase: {phrase}",
            )

    def test_orchestrator_requires_state_verification(self) -> None:
        orchestrator = self.read("01-orchestrator/SKILL.md")
        self.assertIn("Invoke state-verification", orchestrator)
        self.assertIn("user claim", orchestrator)
        self.assertIn("observed fact", orchestrator)
        self.assertIn("authoritative evidence", orchestrator)

    def test_offline_policy_does_not_allow_fabricating_current_state(self) -> None:
        skill = self.read("skills/state-verification/SKILL.md")
        self.assertIn("do not claim that remote state is current", skill)
        self.assertIn("do not claim current external compatibility", self.read("skills/version-verification/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
