import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "tools"))

from security_review import assess_repository  # noqa: E402
from evidence_contract import read_and_validate_evidence  # noqa: E402


class SecurityReviewTests(unittest.TestCase):
    def test_cli_can_emit_canonical_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github" / "workflows" / "safe.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "name: safe\n"
                "permissions:\n"
                "  contents: read\n",
                encoding="utf-8",
            )
            output = root / "security-evidence.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "security_review.py"),
                    str(root),
                    "--canonical-evidence-output",
                    str(output),
                    "--revision",
                    "3872d1e1e6766acf0e6efa9031c6c94edb49571b",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn('"status": "ready"', completed.stdout)
            evidence = read_and_validate_evidence(output)
            self.assertEqual("security-review", evidence.kind)
            self.assertEqual("verified", evidence.status)
            self.assertEqual(
                "3872d1e1e6766acf0e6efa9031c6c94edb49571b",
                evidence.revision,
            )


    def test_current_repository_has_no_high_severity_findings(self):
        result = assess_repository(ROOT)
        self.assertEqual("ready", result.status)
        self.assertEqual(
            0,
            sum(finding.severity == "high" for finding in result.findings),
        )

    def test_blocks_pull_request_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github" / "workflows" / "unsafe.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "name: unsafe\n"
                "on:\n"
                "  pull_request_target:\n"
                "permissions:\n"
                "  contents: read\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "workflow.untrusted-trigger" for f in result.findings)
            )

    def test_blocks_missing_explicit_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github" / "workflows" / "missing-permissions.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "name: missing-permissions\n"
                "on: push\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "workflow.permissions-explicit" for f in result.findings)
            )

    def test_blocks_unpinned_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github" / "workflows" / "unpinned.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "name: unpinned\n"
                "permissions:\n"
                "  contents: read\n"
                "steps:\n"
                "  - uses: actions/checkout@v7\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "workflow.unpinned-action" for f in result.findings)
            )

    def test_flags_write_permission_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github" / "workflows" / "write.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "name: write\n"
                "permissions:\n"
                "  contents: write\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("ready", result.status)
            self.assertTrue(
                any(f.rule_id == "workflow.permissions-write" for f in result.findings)
            )

    def test_blocks_subprocess_shell_true(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "unsafe.py").write_text(
                "import subprocess\n"
                "subprocess.run('echo unsafe', shell=True)\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "python.subprocess-shell" for f in result.findings)
            )

    def test_blocks_force_push_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "unsafe.py").write_text(
                "import subprocess\n"
                "subprocess.run(['git', 'push', '--force', 'origin', 'main'])\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "git.force-push" for f in result.findings)
            )

    def test_blocks_force_true_git_ref_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "unsafe.py").write_text(
                "def update():\n"
                "    payload = {'force': True}\n"
                "    return payload\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "git.force-update" for f in result.findings)
            )

    def test_blocks_direct_protected_ref_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "unsafe.py").write_text(
                "def _request(method, path):\n"
                "    return method, path\n"
                "def update():\n"
                "    return _request('POST', 'refs/heads/main')\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "git.protected-direct-write" for f in result.findings)
            )

    def test_blocks_symlinked_security_review_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            outside = root.parent / f"{root.name}-outside.py"
            outside.write_text("SECRET = 'not-a-review-input'\n", encoding="utf-8")
            link = tools / "linked.py"

            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            self.addCleanup(outside.unlink, missing_ok=True)

            with self.assertRaisesRegex(
                Exception,
                "symbolic link",
            ):
                assess_repository(root)

    def test_blocks_symlinked_review_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / f"{root.name}-tools"
            outside.mkdir()
            tools_link = root / "tools"

            try:
                tools_link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            self.addCleanup(outside.rmdir)

            with self.assertRaisesRegex(
                Exception,
                "symbolic link",
            ):
                assess_repository(root)

    def test_blocks_github_api_without_explicit_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "unsafe.py").write_text(
                "API = 'https://api.github.com'\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "github.api-version" for f in result.findings)
            )

    def test_reports_findings_deterministically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github" / "workflows" / "unsafe.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "name: unsafe\n"
                "on:\n"
                "  pull_request_target:\n"
                "permissions:\n"
                "  contents: write\n"
                "steps:\n"
                "  - uses: actions/checkout@v7\n",
                encoding="utf-8",
            )

            first = assess_repository(root)
            second = assess_repository(root)
            self.assertEqual(
                [finding.__dict__ if hasattr(finding, "__dict__") else (
                    finding.rule_id,
                    finding.severity,
                    finding.path,
                    finding.message,
                    finding.line,
                ) for finding in first.findings],
                [finding.__dict__ if hasattr(finding, "__dict__") else (
                    finding.rule_id,
                    finding.severity,
                    finding.path,
                    finding.message,
                    finding.line,
                ) for finding in second.findings],
            )


if __name__ == "__main__":
    unittest.main()
