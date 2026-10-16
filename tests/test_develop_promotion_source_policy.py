import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CANONICAL_FILES = (
    ROOT / "AGENTS.md",
    ROOT / "01-orchestrator/SKILL.md",
    ROOT / "06-git-github/branching-policy.md",
    ROOT / "docs/governance/promotion-checkpoints.md",
    ROOT / "docs/architecture/promotion.md",
    ROOT / "README.md",
    ROOT / "skills/workflows/promotion-synchronization/SKILL.md",
    ROOT / "tools/develop_promotion.py",
    ROOT / "tools/promotion_sync.py",
    ROOT / "tools/promotion_snapshot.py",
)

DEVELOP_SNAPSHOT_RE = re.compile(
    r"ai/(?:<[^>]+>|\\{[^}]+\\}|[A-Za-z0-9_.-]+)-develop-promotion"
)


class DevelopPromotionSourcePolicyTests(unittest.TestCase):
    def test_canonical_files_do_not_use_temporary_develop_promotion_source(self):
        findings = []
        for path in CANONICAL_FILES:
            text = path.read_text(encoding="utf-8")
            match = DEVELOP_SNAPSHOT_RE.search(text)
            if match:
                findings.append(f"{path.relative_to(ROOT)}: {match.group(0)}")

        self.assertEqual([], findings)

    def test_develop_promotion_is_direct_from_integration(self):
        branching = (ROOT / "06-git-github/branching-policy.md").read_text(
            encoding="utf-8"
        )
        promotion = (ROOT / "docs/architecture/promotion.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("ai/integration -> develop", branching)
        self.assertIn(
            "Develop promotion is an explicit owner-gated pull request",
            promotion,
        )

    def test_main_snapshot_branch_remains_allowed(self):
        snapshot = (ROOT / "tools/promotion_snapshot.py").read_text(
            encoding="utf-8"
        )
        promotion = (ROOT / "docs/architecture/promotion.md").read_text(
            encoding="utf-8"
        )
        self.assertIn('TARGETS = frozenset({"main"})', snapshot)
        self.assertNotIn('TARGETS = frozenset({"develop", "main"})', snapshot)
        self.assertIn("main-promotion", promotion)


if __name__ == "__main__":
    unittest.main()
