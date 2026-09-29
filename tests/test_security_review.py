import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "tools"))

from security_review import SecurityReviewError, assess_repository  # noqa: E402
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
                SecurityReviewError,
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

    def test_accepts_shared_github_api_version_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "safe.py").write_text(
                "API = 'https://api.github.com'\n"
                "from github_http_security import github_api_headers\n"
                "HEADERS = github_api_headers()\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("ready", result.status)
            self.assertFalse(
                any(f.rule_id == "github.api-version" for f in result.findings)
            )

    def test_does_not_accept_textual_shared_header_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "unsafe.py").write_text(
                "# github_api_headers()\n"
                "REFERENCE = \"github_api_headers()\"\n"
                "API = \"https://api.github.com\"\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "github.api-version" for f in result.findings)
            )

    def test_ignores_shared_github_header_policy_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "github_http_security.py").write_text(
                "GITHUB_API_ORIGIN = \"https://api.github.com\"\n"
                "GITHUB_API_VERSION = \"2026-03-10\"\n"
                "def github_api_headers():\n"
                "    return {\"X-GitHub-Api-Version\": GITHUB_API_VERSION}\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertFalse(
                any(f.rule_id == "github.api-version" for f in result.findings)
            )

    def test_accepts_executable_explicit_api_version_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "safe.py").write_text(
                "API = \"https://api.github.com\"\n"
                "HEADERS = {\"X-GitHub-Api-Version\": \"2026-03-10\"}\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("ready", result.status)
            self.assertFalse(
                any(f.rule_id == "github.api-version" for f in result.findings)
            )

    def test_does_not_accept_textual_api_version_header_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir(parents=True)
            (tools / "unsafe.py").write_text(
                "# X-GitHub-Api-Version\n"
                "REFERENCE = \"X-GitHub-Api-Version\"\n"
                "API = \"https://api.github.com\"\n",
                encoding="utf-8",
            )

            result = assess_repository(root)
            self.assertEqual("blocked", result.status)
            self.assertTrue(
                any(f.rule_id == "github.api-version" for f in result.findings)
            )

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
