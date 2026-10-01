import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap_project


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


    def test_structural_validator_rejects_duplicate_metadata_keys(self) -> None:
        import validate_aegis

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(
                '{"version":"0.1.0-alpha.1","version":"0.1.0-alpha.1"}',
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                validate_aegis.load_metadata(path)

    def test_bootstrapped_agent_instructions_require_refresh_checkpoints(self) -> None:
        template = self.read("templates/AGENTS.md")
        self.assertIn("Instruction refresh checkpoints", template)
        self.assertIn("after every three substantial engineering phases", template)
        self.assertIn("immediately before pull-request creation or merge", template)
        self.assertIn("immediately before protected-branch promotion or task completion", template)

    def test_bootstrap_backup_rejects_symlinked_managed_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            target_root = project / ".agents" / "skills"
            state_path = project / ".aegis" / "aegis-version.json"
            backup_root = root / "backup"
            project.mkdir()
            target_root.mkdir(parents=True)
            external = root / "external-skill"
            external.mkdir()
            (external / "SKILL.md").write_text("external\n", encoding="utf-8")
            managed = target_root / "aegis-orchestrator"
            try:
                managed.symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaisesRegex(SystemExit, "symlinked Aegis skill"):
                bootstrap_project.backup_paths(
                    project,
                    target_root,
                    state_path,
                    {"aegis-orchestrator"},
                    backup_root,
                )
            self.assertFalse((backup_root / "skills" / "aegis-orchestrator").exists())

    def test_pull_request_template_matches_language_and_evidence_contract(self) -> None:
        import validate_aegis

        template = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
        validate_aegis.validate_pull_request_template(template)

    def test_bootstrap_registry_paths_stay_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.1.0-alpha.1\n", encoding="utf-8")
            (root / "aegis-manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "repository": "test",
                        "default_work_item_provider": "github",
                        "work_item_strategy": "issues",
                        "optional_integrations": [],
                        "active_knowledge_model": "repository",
                    }
                ),
                encoding="utf-8",
            )
            skills = root / "skills"
            skills.mkdir()
            (skills / "safe.md").write_text("safe\n", encoding="utf-8")
            registry = skills / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "skills": [
                            {"name": "safe", "path": "skills/safe.md"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            version, manifest, loaded_registry = bootstrap_project.load_source_metadata(root)
            self.assertEqual("0.1.0-alpha.1", version)
            self.assertEqual("0.1.0-alpha.1", manifest["version"])
            self.assertEqual("safe", loaded_registry["skills"][0]["name"])

    def test_bootstrap_rejects_registry_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.1.0-alpha.1\n", encoding="utf-8")
            (root / "aegis-manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "repository": "test",
                        "default_work_item_provider": "github",
                        "work_item_strategy": "issues",
                        "optional_integrations": [],
                        "active_knowledge_model": "repository",
                    }
                ),
                encoding="utf-8",
            )
            skills = root / "skills"
            skills.mkdir()
            (skills / "registry.json").write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "skills": [{"name": "external", "path": str(root.parent / "outside.md")}],
                    }
                ),
                encoding="utf-8",
            )
            (root.parent / "outside.md").write_text("outside\n", encoding="utf-8")
            self.addCleanup((root.parent / "outside.md").unlink, missing_ok=True)

            with self.assertRaisesRegex(SystemExit, "relative source path"):
                bootstrap_project.load_source_metadata(root)


    def test_bootstrap_rejects_registry_traversal_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.1.0-alpha.1\n", encoding="utf-8")
            (root / "aegis-manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "repository": "test",
                        "default_work_item_provider": "github",
                        "work_item_strategy": "issues",
                        "optional_integrations": [],
                        "active_knowledge_model": "repository",
                    }
                ),
                encoding="utf-8",
            )
            skills = root / "skills"
            skills.mkdir()
            outside = root.parent / f"{root.name}-outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)
            (skills / "registry.json").write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "skills": [{"name": "external", "path": f"../{outside.name}"}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "relative source path"):
                bootstrap_project.load_source_metadata(root)

    def test_bootstrap_rejects_registry_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("0.1.0-alpha.1\n", encoding="utf-8")
            (root / "aegis-manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "repository": "test",
                        "default_work_item_provider": "github",
                        "work_item_strategy": "issues",
                        "optional_integrations": [],
                        "active_knowledge_model": "repository",
                    }
                ),
                encoding="utf-8",
            )
            skills = root / "skills"
            skills.mkdir()
            outside = root.parent / f"{root.name}-outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            link = skills / "linked.md"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")
            self.addCleanup(outside.unlink, missing_ok=True)

            registry = skills / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "version": "0.1.0-alpha.1",
                        "skills": [{"name": "linked", "path": "skills/linked.md"}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "symbolic link"):
                bootstrap_project.load_source_metadata(root)

    def test_bootstrap_rejects_symlinked_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / f"{root.name}-version"
            outside.write_text("external-version\n", encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)

            version = root / "VERSION"
            try:
                version.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            (root / "aegis-manifest.json").write_text(
                json.dumps(
                    {
                        "version": "external-version",
                        "repository": "test",
                        "default_work_item_provider": "github",
                        "work_item_strategy": "issues",
                        "optional_integrations": [],
                        "active_knowledge_model": "repository",
                    }
                ),
                encoding="utf-8",
            )
            skills = root / "skills"
            skills.mkdir()
            (skills / "registry.json").write_text(
                json.dumps({"version": "external-version", "skills": []}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "VERSION file.*symbolic link"):
                bootstrap_project.load_source_metadata(root)

    def test_bootstrap_rejects_symlinked_hardcoded_skill_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / f"{root.name}-skill"
            outside.write_text("external skill\n", encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)

            source = root / "skill.md"
            try:
                source.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            stage_root = root / "stage"
            stage_root.mkdir()
            selected = {"example": Path("skill.md")}

            with self.assertRaisesRegex(SystemExit, "skill source.*symbolic link"):
                bootstrap_project.stage_skills(root, selected, stage_root)

            self.assertFalse((stage_root / "example" / "SKILL.md").exists())

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
            self.assertTrue(first_state["agents_managed"])
            self.assertRegex(first_state["agents_sha256"], r"^[0-9a-f]{64}$")
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

    def test_bootstrap_rejects_duplicate_state_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            first = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(first.returncode, 0, first.stderr)

            state_path = project / ".aegis" / "aegis-version.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            duplicate = json.dumps(state, sort_keys=True).replace(
                '"preset": "core"',
                '"preset": "core", "preset": "all"',
                1,
            )
            state_path.write_text(duplicate, encoding="utf-8")

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Duplicate JSON key", result.stderr)

    def test_project_verifier_rejects_duplicate_state_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            bootstrap = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_path = project / ".aegis" / "aegis-version.json"
            state = state_path.read_text(encoding="utf-8")
            duplicate = state.replace(
                '"preset": "core"',
                '"preset": "core", "preset": "all"',
                1,
            )
            state_path.write_text(duplicate, encoding="utf-8")

            result = self.run_tool(VERIFY_PROJECT, project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Duplicate JSON key", result.stderr)

    def test_project_verifier_rejects_symlinked_aegis_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            bootstrap = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            state_root = project / ".aegis"
            real_state = project / ".aegis-real"
            state_root.rename(real_state)
            try:
                state_root.symlink_to(real_state, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            result = self.run_tool(VERIFY_PROJECT, project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symbolic link", result.stderr.lower())

    def test_project_verifier_rejects_symlinked_skill_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            bootstrap = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            skill_root = project / ".agents" / "skills"
            real_skills = project / ".agents" / "skills-real"
            skill_root.rename(real_skills)
            try:
                skill_root.symlink_to(real_skills, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            result = self.run_tool(VERIFY_PROJECT, project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("skills root", result.stderr.lower())

    def test_project_verifier_rejects_symlinked_skill_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            bootstrap = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            skill = project / ".agents" / "skills" / "aegis-orchestrator" / "SKILL.md"
            external = Path(tmp) / "external-skill.md"
            external.write_text(skill.read_text(encoding="utf-8"), encoding="utf-8")
            skill.unlink()
            try:
                skill.symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            result = self.run_tool(VERIFY_PROJECT, project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("skill file", result.stderr.lower())

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

    def test_symlinked_agents_root_is_rejected_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            external = Path(tmp) / "external-agents"
            project.mkdir()
            external.mkdir()
            agents_root = project / ".agents"
            try:
                agents_root.symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlinked .agents/skills", result.stderr)
            self.assertFalse(list(external.iterdir()))
            self.assertFalse((project / ".aegis").exists())

    def test_symlinked_aegis_root_is_rejected_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            external = Path(tmp) / "external-aegis"
            project.mkdir()
            external.mkdir()
            state_root = project / ".aegis"
            try:
                state_root.symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlinked .aegis", result.stderr)
            self.assertFalse(list(external.iterdir()))
            self.assertTrue(state_root.is_symlink())

    def test_bootstrap_install_does_not_use_path_based_destination_mkdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            destination_parent = (
                project / ".agents" / "skills" / "aegis-orchestrator"
            )
            real_mkdir = Path.mkdir

            def guarded_mkdir(self, *args, **kwargs):
                if self == destination_parent:
                    raise AssertionError(
                        "managed skill installation must use the anchored atomic writer "
                        "for destination-directory creation"
                    )
                return real_mkdir(self, *args, **kwargs)

            with patch.object(Path, "mkdir", guarded_mkdir):
                with patch.object(
                    sys,
                    "argv",
                    [str(BOOTSTRAP), str(project), "--preset", "core"],
                ):
                    self.assertEqual(0, bootstrap_project.main())

            skill = destination_parent / "SKILL.md"
            self.assertTrue(skill.is_file())
            self.assertFalse(skill.is_symlink())

    def test_bootstrap_managed_skill_install_is_safe_against_destination_symlink_race(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            external = Path(tmp) / "external-skill.md"
            external.write_text("external content\n", encoding="utf-8")
            real_replace = os.replace
            race_triggered = False

            def race_replace(
                source,
                destination,
                *,
                src_dir_fd=None,
                dst_dir_fd=None,
            ):
                nonlocal race_triggered
                if destination == "SKILL.md" and not race_triggered:
                    output = project / ".agents" / "skills" / "aegis-orchestrator" / "SKILL.md"
                    output.symlink_to(external)
                    race_triggered = True
                return real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            import bootstrap_project  # noqa: E402

            with patch("evidence_contract.os.replace", side_effect=race_replace):
                with patch.object(
                    sys,
                    "argv",
                    [str(BOOTSTRAP), str(project), "--preset", "core"],
                ):
                    self.assertEqual(0, bootstrap_project.main())

            self.assertTrue(race_triggered)
            skill = project / ".agents" / "skills" / "aegis-orchestrator" / "SKILL.md"
            self.assertFalse(skill.is_symlink())
            self.assertEqual("external content\n", external.read_text(encoding="utf-8"))
            self.assertNotEqual("external content\n", skill.read_text(encoding="utf-8"))

    def test_symlinked_managed_skill_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            bootstrap = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            external = Path(tmp) / "external-skill.md"
            external.write_text("external content\n", encoding="utf-8")

            managed = project / ".agents" / "skills" / "aegis-orchestrator" / "SKILL.md"
            managed.unlink()
            managed.symlink_to(external)

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlinked aegis skill file", result.stderr.lower())
            self.assertEqual("external content\n", external.read_text(encoding="utf-8"))

    def test_broken_symlink_skill_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            missing_target = Path(tmp) / "missing-skill"
            skill_target = project / ".agents" / "skills" / "github-issues"
            skill_target.parent.mkdir(parents=True, exist_ok=True)
            try:
                skill_target.symlink_to(missing_target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlinked project skill target", result.stderr.lower())
            self.assertTrue(skill_target.is_symlink())

    def test_broken_symlink_managed_skill_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            first = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(first.returncode, 0, first.stderr)

            managed = project / ".agents" / "skills" / "aegis-orchestrator"
            managed_target = Path(tmp) / "missing-managed-skill"
            shutil.rmtree(managed)
            try:
                managed.symlink_to(managed_target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlinked aegis skill path", result.stderr.lower())
            self.assertTrue(managed.is_symlink())

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

    def test_project_verifier_detects_managed_agents_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            bootstrap = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)

            verified = self.run_tool(VERIFY_PROJECT, project)
            self.assertEqual(verified.returncode, 0, verified.stderr)

            agents = project / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8") + "\n# Tampered\n",
                encoding="utf-8",
            )

            tampered = self.run_tool(VERIFY_PROJECT, project)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("Managed AGENTS.md checksum mismatch", tampered.stderr)

    def test_bootstrap_refuses_modified_managed_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            first = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(first.returncode, 0, first.stderr)

            agents = project / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8") + "\n# Project mutation\n",
                encoding="utf-8",
            )
            original = agents.read_text(encoding="utf-8")

            second = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("customized managed AGENTS.md", second.stderr)
            self.assertEqual(original, agents.read_text(encoding="utf-8"))

    def test_legacy_agents_classification_uses_one_hash_snapshot(self) -> None:
        import sys as _sys

        sys_path = str(ROOT / "tools")
        if sys_path not in _sys.path:
            _sys.path.insert(0, sys_path)
        import bootstrap_project  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            template = root / "template-AGENTS.md"
            content = "canonical instructions\n"
            agents.write_text(content, encoding="utf-8")
            template.write_text(content, encoding="utf-8")

            original = bootstrap_project.sha256_file
            calls = []

            def counted(path: Path) -> str:
                calls.append(path)
                return original(path)

            with patch.object(
                bootstrap_project,
                "sha256_file",
                side_effect=counted,
            ):
                managed, checksum = bootstrap_project.inspect_agents_state(
                    agents,
                    template,
                    None,
                )

            self.assertTrue(managed)
            self.assertEqual(original(agents), checksum)
            self.assertEqual(1, calls.count(agents))
            self.assertEqual(1, calls.count(template))

    def test_user_owned_agents_is_not_claimed_as_aegis_managed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            agents = project / "AGENTS.md"
            agents.write_text(
                "Project-owned instructions\n",
                encoding="utf-8",
            )

            first = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(first.returncode, 0, first.stderr)

            state = json.loads(
                (project / ".aegis" / "aegis-version.json").read_text(encoding="utf-8")
            )
            self.assertFalse(state["agents_managed"])
            self.assertIsNone(state["agents_sha256"])
            self.assertEqual(
                "Project-owned instructions\n",
                agents.read_text(encoding="utf-8"),
            )

    def test_symlinked_managed_agents_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            first = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertEqual(first.returncode, 0, first.stderr)

            state_path = project / ".aegis" / "aegis-version.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(state["agents_managed"])

            external = Path(tmp) / "external-agents.md"
            external.write_text("external\n", encoding="utf-8")
            agents = project / "AGENTS.md"
            agents.unlink()
            agents.symlink_to(external)

            result = self.run_tool(BOOTSTRAP, project, "--preset", "core")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlinked AGENTS.md", result.stderr)
            self.assertEqual("external\n", external.read_text(encoding="utf-8"))


    def test_bootstrap_state_writer_is_anchored_against_parent_symlink_race(self) -> None:
        if os.name != "posix":
            self.skipTest("directory-FD anchoring is only available on POSIX.")

        import bootstrap_project  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root = root / "state"
            moved_root = root / "state-original"
            external = root / "external"
            state_root.mkdir()
            external.mkdir()
            state_path = state_root / "aegis-version.json"
            payload = {"schema_version": 2, "status": "active"}

            real_replace = os.replace

            def race_replace(
                source,
                destination,
                *,
                src_dir_fd=None,
                dst_dir_fd=None,
            ):
                state_root.rename(moved_root)
                state_root.symlink_to(external, target_is_directory=True)
                return real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with patch("evidence_contract.os.replace", side_effect=race_replace):
                bootstrap_project.write_state_atomically(state_path, payload)

            self.assertFalse((external / state_path.name).exists())
            self.assertEqual(
                payload,
                json.loads(
                    (moved_root / state_path.name).read_text(encoding="utf-8")
                ),
            )
            self.assertTrue(state_root.is_symlink())

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


    def test_bootstrap_source_checkpoint_rejects_head_change(self) -> None:
        import bootstrap_project  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "aegis-source"
            source.mkdir()
            subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "aegis-tests@example.invalid"],
                cwd=source,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Aegis Tests"],
                cwd=source,
                check=True,
                capture_output=True,
            )

            tracked = source / "VERSION"
            tracked.write_text("0.1.0-alpha.1\n", encoding="utf-8")
            subprocess.run(["git", "add", "VERSION"], cwd=source, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "test: initial source"],
                cwd=source,
                check=True,
                capture_output=True,
            )

            checkpoint = bootstrap_project.read_source_commit(source)

            tracked.write_text("0.1.0-alpha.2\n", encoding="utf-8")
            subprocess.run(["git", "add", "VERSION"], cwd=source, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "test: advance source"],
                cwd=source,
                check=True,
                capture_output=True,
            )

            with self.assertRaisesRegex(
                SystemExit,
                "source commit changed during bootstrap",
            ):
                bootstrap_project.verify_source_checkpoint(source, checkpoint)

    def test_bootstrap_rejects_target_inside_aegis_source(self) -> None:
        target = ROOT / ".aegis-audit-forbidden-target"
        result = self.run_tool(BOOTSTRAP, target, "--preset", "core")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inside the aegis source repository", result.stderr.lower())

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
