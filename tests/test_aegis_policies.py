import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "tools" / "bootstrap_project.py"
VERIFY_PROJECT = ROOT / "tools" / "verify_project.py"


class AegisPolicyTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def run_tool(
        self,
        tool: Path,
        project: Path,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(tool), str(project), *args],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_state_verification_skill_exists_and_is_registered(self) -> None:
        skill_path = ROOT / "skills/state-verification/SKILL.md"
        self.assertTrue(skill_path.is_file())

        registry = json.loads(self.read("skills/registry.json"))
        entries = {entry["name"]: entry["path"] for entry in registry["skills"]}
        self.assertEqual(
            entries.get("state-verification"),
            "skills/state-verification/SKILL.md",
        )

    def test_user_claims_are_not_external_state_evidence(self) -> None:
        combined = "\n".join(
            (
                self.read("AGENTS.md"),
                self.read("00-constitution/core-principles.md"),
                self.read("skills/state-verification/SKILL.md"),
            )
        )

        required_phrases = (
            "not proof of independently observable state",
            "Verify current state from the strongest available authoritative source",
            "read the resulting state back",
            "Distinguish verified facts, user-provided claims, assumptions",
        )

        for phrase in required_phrases:
            self.assertIn(phrase, combined)

    def test_orchestrator_requires_state_verification(self) -> None:
        orchestrator = self.read("01-orchestrator/SKILL.md")
        self.assertIn("Invoke state-verification", orchestrator)
        self.assertIn("user claim", orchestrator)
        self.assertIn("observed fact", orchestrator)
        self.assertIn("authoritative evidence", orchestrator)

    def test_offline_policy_does_not_allow_fabricating_current_state(self) -> None:
        state_skill = self.read("skills/state-verification/SKILL.md")
        version_skill = self.read("skills/version-verification/SKILL.md")

        self.assertIn("do not claim that remote state is current", state_skill.lower())
        self.assertIn(
            "do not claim current external compatibility without evidence",
            version_skill.lower(),
        )

    def test_bootstrap_all_records_effective_state_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            first = self.run_tool(BOOTSTRAP, project, "--preset", "all")
            self.assertEqual(first.returncode, 0, first.stderr)

            state_path = project / ".aegis" / "aegis-version.json"
            first_state = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertEqual(first_state["schema_version"], 2)
            self.assertEqual(first_state["source_worktree_clean"], True)
            self.assertEqual(first_state["preset"], "all")
            self.assertEqual(first_state["integrations"], ["confluence", "jira"])
            self.assertEqual(
                first_state["skills"],
                sorted(first_state["skill_checksums"]),
            )
            self.assertEqual(len(first_state["skills"]), 25)

            second = self.run_tool(BOOTSTRAP, project, "--preset", "all")
            self.assertEqual(second.returncode, 0, second.stderr)

            second_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(first_state, second_state)

    def test_bootstrap_reconciles_previous_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            first = self.run_tool(BOOTSTRAP, project, "--preset", "all")
            self.assertEqual(first.returncode, 0, first.stderr)

            custom = project / ".agents" / "skills" / "custom-project-skill" / "SKILL.md"
            custom.parent.mkdir(parents=True, exist_ok=True)
            custom.write_text(
                "---\nname: custom-project-skill\ndescription: Project-local skill.\n---\n",
                encoding="utf-8",
            )

            second = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(second.returncode, 0, second.stderr)

            self.assertTrue(custom.is_file())
            self.assertFalse(
                (project / ".agents" / "skills" / "jira").exists()
            )
            self.assertFalse(
                (project / ".agents" / "skills" / "confluence").exists()
            )

            verified = self.run_tool(VERIFY_PROJECT, project)
            self.assertEqual(verified.returncode, 0, verified.stderr)

            state = json.loads(
                (project / ".aegis" / "aegis-version.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["preset"], "core")
            self.assertNotIn("jira", state["skills"])
            self.assertNotIn("confluence", state["skills"])

            dry_run = self.run_tool(BOOTSTRAP, project, "--preset", "all", "--dry-run")
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertIn("Would install", dry_run.stdout)

    def test_unowned_skill_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            existing = project / ".agents" / "skills" / "github-issues" / "SKILL.md"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("project-owned skill\n", encoding="utf-8")

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unowned project skill", result.stderr.lower())
            self.assertEqual(existing.read_text(encoding="utf-8"), "project-owned skill\n")
            self.assertFalse((project / ".aegis").exists())

    def test_customized_managed_skill_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            first = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(first.returncode, 0, first.stderr)

            skill = project / ".agents" / "skills" / "aegis-orchestrator" / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8") + "\n# Project customization\n",
                encoding="utf-8",
            )

            state_path = project / ".aegis" / "aegis-version.json"
            original_state = state_path.read_text(encoding="utf-8")
            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("customized aegis skill", result.stderr.lower())
            self.assertEqual(state_path.read_text(encoding="utf-8"), original_state)

    def test_dirty_aegis_source_is_rejected_before_project_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "aegis-source"
            target = Path(tmp) / "target"
            target.mkdir()

            created = subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree), "HEAD"],
                cwd=ROOT,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            try:
                source_skill = worktree / "skills" / "state-verification" / "SKILL.md"
                source_skill.write_text(
                    source_skill.read_text(encoding="utf-8") + "\n# Dirty\n",
                    encoding="utf-8",
                )

                result = self.run_tool(
                    worktree / "tools" / "bootstrap_project.py",
                    target,
                    "--preset",
                    "core",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("worktree is dirty", result.stderr.lower())
                self.assertFalse((target / ".agents").exists())
                self.assertFalse((target / ".aegis").exists())
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )

    def test_project_verifier_detects_skill_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            bootstrap = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            verified = self.run_tool(VERIFY_PROJECT, project)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertIn("verification passed", verified.stdout.lower())

            skill = project / ".agents" / "skills" / "aegis-orchestrator" / "SKILL.md"
            with skill.open("a", encoding="utf-8") as handle:
                handle.write("\n# Tampered\n")

            tampered = self.run_tool(VERIFY_PROJECT, project)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("checksum mismatch", tampered.stderr.lower())


if __name__ == "__main__":
    unittest.main()
