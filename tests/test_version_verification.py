import hashlib
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from version_verification import (  # noqa: E402
    VersionVerificationError,
    record_version_evidence,
    validate_version_evidence,
)


class VersionVerificationTests(unittest.TestCase):
    def _project(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "pyproject.toml").write_text(
            '[project]\nrequires-python = ">=3.13"\n',
            encoding="utf-8",
        )
        (root / "gradle.properties").write_text(
            "kotlin.version=2.2.20\n",
            encoding="utf-8",
        )
        claims = root / "claims.json"
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "python",
                            "version": "3.13",
                            "scope": "language",
                            "source": "pyproject.toml",
                        },
                        {
                            "component": "kotlin",
                            "version": "2.2.20",
                            "scope": "compiler",
                            "source": "gradle.properties",
                        },
                    ],
                    "external_verification_pending": False,
                }
            ),
            encoding="utf-8",
        )
        self.addCleanup(temp.cleanup)
        return root, claims

    def test_record_creates_sha_pinned_deterministic_evidence(self):
        root, claims = self._project()
        output = root / ".aegis" / "version-evidence.json"

        first = record_version_evidence(root, claims, output)
        second = record_version_evidence(root, claims, output)

        self.assertEqual(first, second)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(2, len(payload["claims"]))
        digest = hashlib.sha256(
            (root / "pyproject.toml").read_bytes()
        ).hexdigest()
        self.assertEqual(digest, payload["claims"][0]["source_sha256"])

    def test_validate_rejects_source_drift(self):
        root, claims = self._project()
        output = root / ".aegis" / "version-evidence.json"
        record_version_evidence(root, claims, output)

        (root / "pyproject.toml").write_text(
            '[project]\nrequires-python = ">=3.14"\n',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(VersionVerificationError, "SHA-256 changed"):
            validate_version_evidence(root, output)

    def test_validate_rejects_version_not_present_in_source(self):
        root, claims = self._project()
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "python",
                            "version": "9.99",
                            "scope": "language",
                            "source": "pyproject.toml",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        output = root / ".aegis" / "version-evidence.json"

        with self.assertRaisesRegex(VersionVerificationError, "was not found"):
            record_version_evidence(root, claims, output)

    def test_source_path_must_stay_inside_project(self):
        root, _ = self._project()
        claims = root / "claims.json"
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "external",
                            "version": "1.0",
                            "scope": "other",
                            "source": "../outside.txt",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        output = root / ".aegis" / "version-evidence.json"

        with self.assertRaisesRegex(VersionVerificationError, "inside the project root"):
            record_version_evidence(root, claims, output)

    def test_duplicate_component_claims_are_rejected(self):
        root, _ = self._project()
        claims = root / "claims.json"
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "python",
                            "version": "3.13",
                            "scope": "language",
                            "source": "pyproject.toml",
                        },
                        {
                            "component": "python",
                            "version": "3.13",
                            "scope": "runtime",
                            "source": "pyproject.toml",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(VersionVerificationError, "Duplicate"):
            record_version_evidence(
                root,
                claims,
                root / ".aegis" / "version-evidence.json",
            )

    def test_pending_flag_must_be_boolean(self):
        root, claims = self._project()
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "python",
                            "version": "3.13",
                            "scope": "language",
                            "source": "pyproject.toml",
                        }
                    ],
                    "external_verification_pending": "yes",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(VersionVerificationError, "must be boolean"):
            record_version_evidence(
                root,
                claims,
                root / ".aegis" / "version-evidence.json",
            )

    def test_cli_validate_can_emit_canonical_evidence(self):
        root, claims = self._project()
        output = root / ".aegis" / "version-evidence.json"
        canonical = root / ".aegis" / "canonical-version-evidence.json"
        record_version_evidence(root, claims, output)

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "version_verification.py"),
                "validate",
                str(root),
                str(output),
                "--revision",
                "7c2d2247abf2d4463a2167d20e7ab18a808a24ee",
                "--evidence-output",
                str(canonical),
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn('"external_verification_pending": false', completed.stdout)
        payload = json.loads(canonical.read_text(encoding="utf-8"))
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("version-verification", payload["kind"])
        self.assertEqual(
            "7c2d2247abf2d4463a2167d20e7ab18a808a24ee",
            payload["revision"],
        )
        self.assertEqual("verified", payload["status"])
        self.assertEqual(
            output.relative_to(root).as_posix(),
            " .aegis/version-evidence.json".strip(),
        )
        self.assertEqual(
            "2.2.20",
            next(
                claim["version"]
                for claim in payload["result"]["claims"]
                if claim["component"] == "kotlin"
            ),
        )

    def test_record_refuses_to_overwrite_input_or_source(self):
        root, claims = self._project()
        with self.assertRaisesRegex(VersionVerificationError, "differ"):
            record_version_evidence(root, claims, claims)

        with self.assertRaisesRegex(VersionVerificationError, "overwrite"):
            record_version_evidence(
                root,
                claims,
                root / "pyproject.toml",
            )

    def test_external_verification_pending_is_preserved(self):
        root, claims = self._project()
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "python",
                            "version": "3.13",
                            "scope": "language",
                            "source": "pyproject.toml",
                        }
                    ],
                    "external_verification_pending": True,
                }
            ),
            encoding="utf-8",
        )
        evidence = record_version_evidence(
            root,
            claims,
            root / ".aegis" / "version-evidence.json",
        )
        self.assertTrue(evidence.external_verification_pending)
        validated = validate_version_evidence(
            root,
            root / ".aegis" / "version-evidence.json",
        )
        self.assertTrue(validated.external_verification_pending)


if __name__ == "__main__":
    unittest.main()
