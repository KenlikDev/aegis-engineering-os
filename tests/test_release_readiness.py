import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from release_readiness import (  # noqa: E402
    GitHubReleaseReadinessProvider,
    ReleaseReadinessError,
    assess_release_readiness,
)

REPOSITORY = "KenlikDev/aegis-engineering-os"
MAIN_SHA = "1111111111111111111111111111111111111111"

BASE_FILES = {
    "VERSION": "0.1.0-alpha.1\n",
    "aegis-manifest.json": json.dumps({"version": "0.1.0-alpha.1"}),
    "skills/registry.json": json.dumps(
        {"version": "0.1.0-alpha.1", "skills": []}
    ),
    "CHANGELOG.md": (
        "# Changelog\n\n"
        "## Unreleased\n\n"
        "## 0.1.0-alpha.1\n\n"
        "- Initial foundation.\n"
    ),
}


class FakeTransport:
    def __init__(
        self,
        *,
        protected=True,
        validation=True,
        version=BASE_FILES["VERSION"],
        manifest_version="0.1.0-alpha.1",
        registry_version="0.1.0-alpha.1",
        changelog=BASE_FILES["CHANGELOG.md"],
    ):
        self.protected = protected
        self.validation = validation
        self.version = version
        self.manifest_version = manifest_version
        self.registry_version = registry_version
        self.changelog = changelog
        self.requests = []

    def __call__(self, method, url, headers):
        self.requests.append((method, url, headers))
        if method != "GET":
            raise AssertionError("Release readiness must remain read-only.")

        if url.endswith("/branches/main"):
            return 200, {
                "name": "main",
                "protected": self.protected,
                "commit": {"sha": MAIN_SHA},
            }

        if "/actions/workflows/" in url and "/runs?" in url:
            if not self.validation:
                return 200, {"workflow_runs": []}
            return 200, {
                "workflow_runs": [
                    {
                        "id": 7,
                        "name": "Aegis Validation",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": MAIN_SHA,
                        "html_url": "https://github.com/example/actions/runs/7",
                    }
                ]
            }

        files = {
            "VERSION": self.version,
            "aegis-manifest.json": json.dumps(
                {"version": self.manifest_version}
            ),
            "skills/registry.json": json.dumps(
                {"version": self.registry_version, "skills": []}
            ),
            "CHANGELOG.md": self.changelog,
        }
        for path, content in files.items():
            marker = f"/contents/{path}?ref=main"
            if url.endswith(marker):
                encoded = base64.b64encode(
                    content.encode("utf-8")
                ).decode("ascii")
                return 200, {
                    "encoding": "base64",
                    "content": encoded,
                    "path": path,
                }

        raise AssertionError(f"Unexpected request: {method} {url}")


class ReleaseReadinessTests(unittest.TestCase):
    def _provider(self, transport):
        return GitHubReleaseReadinessProvider(
            REPOSITORY,
            "secret-token",
            transport=transport,
        )

    def test_ready_when_release_contract_is_clean(self):
        transport = FakeTransport()
        result = assess_release_readiness(self._provider(transport))

        self.assertTrue(result.ready)
        self.assertEqual(MAIN_SHA, result.target.sha)
        self.assertEqual("0.1.0-alpha.1", result.version)
        self.assertTrue(result.version_valid)
        self.assertTrue(result.changelog.version_heading_present)
        self.assertTrue(result.changelog.version_section_has_content)
        self.assertFalse(result.changelog.unreleased_content_present)
        self.assertEqual(0, len(result.blockers))
        self.assertTrue(all(request[0] == "GET" for request in transport.requests))

    def test_blocks_unreleased_notes(self):
        changelog = (
            "# Changelog\n\n"
            "## Unreleased\n\n"
            "- Pending note.\n\n"
            "## 0.1.0-alpha.1\n\n"
            "- Initial foundation.\n"
        )
        result = assess_release_readiness(
            self._provider(FakeTransport(changelog=changelog))
        )

        self.assertTrue(result.changelog.unreleased_section_present)
        self.assertTrue(result.changelog.unreleased_content_present)
        self.assertIn(
            "unreleased notes",
            " ".join(result.blockers),
        )

    def test_blocks_unprotected_main(self):
        result = assess_release_readiness(
            self._provider(FakeTransport(protected=False))
        )
        self.assertIn("main must remain protected.", result.blockers)

    def test_blocks_missing_exact_sha_validation(self):
        result = assess_release_readiness(
            self._provider(FakeTransport(validation=False))
        )
        self.assertIn("exact main SHA", " ".join(result.blockers))

    def test_blocks_version_mismatch(self):
        result = assess_release_readiness(
            self._provider(FakeTransport(manifest_version="9.9.9"))
        )
        self.assertIn("VERSION and aegis-manifest.json disagree.", result.blockers)

    def test_blocks_registry_mismatch(self):
        result = assess_release_readiness(
            self._provider(FakeTransport(registry_version="9.9.9"))
        )
        self.assertIn("VERSION and skills/registry.json disagree.", result.blockers)

    def test_blocks_invalid_version(self):
        result = assess_release_readiness(
            self._provider(FakeTransport(version="not-a-version\n"))
        )
        self.assertIn("invalid release version", " ".join(result.blockers))

    def test_blocks_missing_changelog_heading(self):
        changelog = (
            "# Changelog\n\n"
            "## Unreleased\n\n"
            "## 9.9.9\n\n"
            "- Wrong version.\n"
        )
        result = assess_release_readiness(
            self._provider(FakeTransport(changelog=changelog))
        )
        self.assertIn(
            "does not contain a version heading",
            " ".join(result.blockers),
        )

    def test_blocks_empty_changelog_version_section(self):
        changelog = "# Changelog\n\n## Unreleased\n\n## 0.1.0-alpha.1\n"
        result = assess_release_readiness(
            self._provider(FakeTransport(changelog=changelog))
        )
        self.assertIn(
            "version section for 0.1.0-alpha.1 is empty",
            result.blockers,
        )

    def test_rejects_non_main_target_before_network_access(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "target must be main",
        ):
            assess_release_readiness(
                self._provider(transport),
                target_branch="develop",
            )
        self.assertEqual([], transport.requests)


if __name__ == "__main__":
    unittest.main()
