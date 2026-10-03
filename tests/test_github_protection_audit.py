import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from github_protection_audit import (  # noqa: E402
    DEFAULT_BRANCHES,
    GitHubRulesetProvider,
    RulesetAuditError,
    audit_branches,
    build_audit_evidence,
    summarize_ruleset,
)


def ruleset(*, ruleset_id=1, name="develop-protection", branch="develop"):
    return {
        "id": ruleset_id,
        "name": name,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [f"refs/heads/{branch}"],
                "exclude": [],
            }
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["squash"],
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": "Validate Aegis", "integration_id": 15368}
                    ],
                },
            },
            {"type": "required_linear_history"},
        ],
        "bypass_actors": [],
        "_links": {
            "html": {
                "href": f"https://github.com/KenlikDev/aegis-engineering-os/rules/{ruleset_id}"
            }
        },
    }


class FakeProvider:
    repository = "KenlikDev/aegis-engineering-os"

    def __init__(self, items):
        self.items = items

    def list_active_rulesets(self):
        return list(self.items)


class FakeTransport:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, method, url, headers, payload):
        self.calls.append((method, url, payload))
        page = int(url.split("page=")[-1])
        return 200, self.pages.get(page, [])


class ProtectionAuditTests(unittest.TestCase):
    def test_summarizes_relevant_controls(self):
        summary = summarize_ruleset(ruleset())
        self.assertEqual(0, summary.required_approving_reviews)
        self.assertEqual(("Validate Aegis",), summary.required_status_checks)
        self.assertTrue(summary.strict_required_status_checks)
        self.assertTrue(summary.requires_conversation_resolution)
        self.assertTrue(summary.blocks_force_push)
        self.assertTrue(summary.blocks_deletion)
        self.assertTrue(summary.requires_linear_history)
        self.assertEqual(("squash",), summary.allowed_merge_methods)
        self.assertEqual((), summary.bypass_actors)

    def test_requires_exactly_one_active_ruleset_per_branch(self):
        with self.assertRaisesRegex(RulesetAuditError, "exactly one"):
            audit_branches(FakeProvider([]), ("develop",))
        with self.assertRaisesRegex(RulesetAuditError, "exactly one"):
            audit_branches(
                FakeProvider([ruleset(), ruleset(ruleset_id=2)]),
                ("develop",),
            )

    def test_ignores_rulesets_for_other_branches(self):
        result = audit_branches(
            FakeProvider([
                ruleset(),
                ruleset(ruleset_id=2, name="main-protection", branch="main"),
            ]),
            ("develop",),
        )
        self.assertEqual(1, result["branches"]["develop"]["ruleset"]["id"])

    def test_rejects_malformed_rule(self):
        malformed = ruleset()
        malformed["rules"].append({"type": "deletion"})
        with self.assertRaisesRegex(RulesetAuditError, "duplicate rule type"):
            summarize_ruleset(malformed)

    def test_rejects_missing_conditions(self):
        malformed = ruleset()
        malformed.pop("conditions")
        with self.assertRaisesRegex(RulesetAuditError, "conditions"):
            summarize_ruleset(malformed)

    def test_reads_all_ruleset_pages(self):
        transport = FakeTransport({
            1: [
                ruleset(ruleset_id=index, name=f"filler-{index}", branch=f"filler-{index}")
                for index in range(1, 101)
            ],
            2: [ruleset(ruleset_id=101, name="main-protection", branch="main")],
            3: [],
        })
        provider = GitHubRulesetProvider(
            "KenlikDev/aegis-engineering-os", "token", transport=transport
        )
        items = provider.list_active_rulesets()
        self.assertEqual(101, len(items))
        self.assertEqual(2, len(transport.calls))

    def test_preserves_unknown_bypass_actor_visibility(self):
        item = ruleset()
        item.pop("bypass_actors")
        summary = summarize_ruleset(item)
        self.assertIsNone(summary.bypass_actors)

    def test_ignores_inactive_and_non_branch_rulesets(self):
        inactive = ruleset(ruleset_id=10)
        inactive["enforcement"] = "evaluate"
        malformed_tag = ruleset(ruleset_id=11)
        malformed_tag["target"] = "tag"
        malformed_tag.pop("conditions")
        result = audit_branches(
            FakeProvider([
                inactive,
                malformed_tag,
                ruleset(),
            ]),
            ("develop",),
        )
        self.assertEqual(1, result["branches"]["develop"]["ruleset"]["id"])

    def test_evidence_is_verified_when_bypass_visibility_is_available(self):
        result = audit_branches(
            FakeProvider([
                ruleset(branch=branch, ruleset_id=index)
                for index, branch in enumerate(DEFAULT_BRANCHES, start=1)
            ])
        )
        evidence = build_audit_evidence(
            result, observed_at="2026-10-03T12:00:00Z"
        )
        self.assertEqual("github-ruleset-audit", evidence.kind)
        self.assertEqual("verified", evidence.status)
        self.assertEqual("github:KenlikDev/aegis-engineering-os", evidence.source)

    def test_evidence_is_unknown_when_bypass_visibility_is_unavailable(self):
        item = ruleset()
        item.pop("bypass_actors")
        result = audit_branches(FakeProvider([item]), ("develop",))
        evidence = build_audit_evidence(
            result, observed_at="2026-10-03T12:00:00Z"
        )
        self.assertEqual("unknown", evidence.status)
        self.assertIn("bypass_actor visibility", evidence.uncertainty[0])

    def test_rejects_invalid_repository_or_token(self):
        with self.assertRaises(RulesetAuditError):
            GitHubRulesetProvider("invalid", "token")
        with self.assertRaises(RulesetAuditError):
            GitHubRulesetProvider("KenlikDev/aegis-engineering-os", "")


if __name__ == "__main__":
    unittest.main()
