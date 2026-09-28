import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_bundle import build_evidence_bundle, write_evidence_bundle
from evidence_bundle_requirements import (
    EvidenceSetRequirementsError,
    load_requirements,
    validate_evidence_set,
)
from evidence_contract import build_evidence, read_and_validate_evidence, write_evidence


def _evidence(kind: str, status: str, subject: str, source: str):
    return build_evidence(
        {
            "schema_version": 1,
            "kind": kind,
            "source": source,
            "subject": subject,
            "revision": "7c2d2247abf2d4463a2167d20e7ab18a808a24ee",
            "observed_at": "2026-09-28T18:00:00Z",
            "status": status,
            "result": {"state": subject},
            "uncertainty": [],
            "references": ["https://github.com/KenlikDev/aegis-engineering-os"],
            "artifact_sha256": None,
        }
    )


class EvidenceSetRequirementsTests(unittest.TestCase):
    def _project(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        evidence_dir = root / ".aegis"
        evidence_dir.mkdir(parents=True)

        readiness = evidence_dir / "readiness.json"
        testing = evidence_dir / "testing.json"
        extra = evidence_dir / "extra.json"
        write_evidence(
            _evidence(
                "implementation-readiness",
                "verified",
                "work-item:132",
                "aegis:implementation-readiness",
            ),
            readiness,
        )
        write_evidence(
            _evidence(
                "testing",
                "verified",
                "project-testing",
                "aegis:testing",
            ),
            testing,
        )
        write_evidence(
            _evidence(
                "security-review",
                "verified",
                "repository-security",
                "aegis:security-review",
            ),
            extra,
        )

        bundle_path = evidence_dir / "bundle.json"
        bundle = build_evidence_bundle(
            root,
            "Explicit readiness evidence",
            [readiness, testing, extra],
        )
        write_evidence_bundle(bundle, root, bundle_path)

        requirements = root / "requirements.json"
        requirements.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "requirements": [
                        {
                            "kind": "implementation-readiness",
                            "status": "verified",
                            "subject": "work-item:132",
                            "source": "aegis:implementation-readiness",
                        },
                        {
                            "kind": "testing",
                            "status": "verified",
                            "subject": "project-testing",
                            "source": "aegis:testing",
                        },
                    ],
                    "allow_extra_members": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.addCleanup(temp.cleanup)
        return root, bundle_path, requirements, readiness, testing, extra

    def test_satisfied_requirements_are_verified(self):
        root, bundle, requirements, *_ = self._project()
        result = validate_evidence_set(root, bundle, requirements)
        self.assertEqual("verified", result.status)
        self.assertEqual(2, result.requirements_satisfied)
        self.assertEqual(2, result.requirements_total)
        self.assertEqual(1, len(result.extra_members))

    def test_missing_requirement_fails_closed(self):
        root, bundle, requirements, *_ = self._project()
        payload = json.loads(requirements.read_text(encoding="utf-8"))
        payload["requirements"][1]["subject"] = "project-testing:missing"
        requirements.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            EvidenceSetRequirementsError,
            "requirements are not satisfied",
        ):
            validate_evidence_set(root, bundle, requirements)

    def test_one_member_cannot_satisfy_two_requirements(self):
        root, bundle, requirements, *_ = self._project()
        payload = json.loads(requirements.read_text(encoding="utf-8"))
        payload["requirements"] = [
            {
                "kind": "implementation-readiness",
                "status": "verified",
                "subject": None,
                "source": None,
            },
            {
                "kind": "implementation-readiness",
                "status": "verified",
                "subject": None,
                "source": None,
            },
        ]
        requirements.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            EvidenceSetRequirementsError,
            "requirements are not satisfied",
        ):
            validate_evidence_set(root, bundle, requirements)

    def test_status_subject_and_source_must_match_when_supplied(self):
        root, bundle, requirements, *_ = self._project()
        payload = json.loads(requirements.read_text(encoding="utf-8"))
        payload["requirements"][0]["status"] = "pending"
        requirements.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            EvidenceSetRequirementsError,
            "requirements are not satisfied",
        ):
            validate_evidence_set(root, bundle, requirements)

    def test_extra_members_are_allowed_by_default_contract(self):
        root, bundle, requirements, *_ = self._project()
        result = validate_evidence_set(root, bundle, requirements)
        self.assertEqual(1, len(result.extra_members))

    def test_extra_members_can_be_rejected(self):
        root, bundle, requirements, *_ = self._project()
        payload = json.loads(requirements.read_text(encoding="utf-8"))
        payload["allow_extra_members"] = False
        requirements.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            EvidenceSetRequirementsError,
            "extra members",
        ):
            validate_evidence_set(root, bundle, requirements)

    def test_malformed_requirements_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "requirements.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "requirements": [],
                        "allow_extra_members": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                EvidenceSetRequirementsError,
                "between 1 and",
            ):
                load_requirements(path)

    def test_duplicate_requirement_selectors_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "requirements.json"
            selector = {
                "kind": "testing",
                "status": "verified",
                "subject": "project-testing",
                "source": "aegis:testing",
            }
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "requirements": [selector, selector],
                        "allow_extra_members": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                EvidenceSetRequirementsError,
                "duplicate selectors",
            ):
                load_requirements(path)

    def test_bundle_tampering_fails_before_requirements_are_checked(self):
        root, bundle, requirements, readiness, *_ = self._project()
        evidence = json.loads(readiness.read_text(encoding="utf-8"))
        evidence["result"]["state"] = "tampered"
        readiness.write_text(json.dumps(evidence), encoding="utf-8")

        with self.assertRaisesRegex(
            EvidenceSetRequirementsError,
            "invalid",
        ):
            validate_evidence_set(root, bundle, requirements)

    def test_requirements_revalidate_member_identity(self):
        root, bundle, requirements, readiness, *_ = self._project()
        evidence = read_and_validate_evidence(readiness)
        replacement = dict(evidence.result)
        replacement["state"] = "replacement"
        write_evidence(
            _evidence(
                "implementation-readiness",
                "verified",
                "work-item:replacement",
                "aegis:implementation-readiness",
            ),
            readiness,
        )

        with self.assertRaisesRegex(
            EvidenceSetRequirementsError,
            "identity",
        ):
            validate_evidence_set(root, bundle, requirements)

    def test_cli_reports_verified_result(self):
        root, bundle, requirements, *_ = self._project()
        output = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "evidence_bundle_requirements.py"),
                str(root),
                str(bundle),
                str(requirements),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(output.stdout)
        self.assertEqual("verified", payload["status"])
        self.assertEqual(2, payload["requirements_satisfied"])

    def test_cli_reports_unsatisfied_requirements_without_secret_values(self):
        root, bundle, requirements, *_ = self._project()
        payload = json.loads(requirements.read_text(encoding="utf-8"))
        payload["requirements"][0]["subject"] = "missing-ghp_FAKESECRET123456789012345"
        requirements.write_text(json.dumps(payload), encoding="utf-8")

        output = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "evidence_bundle_requirements.py"),
                str(root),
                str(bundle),
                str(requirements),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(1, output.returncode)
        self.assertNotIn("ghp_FAKESECRET123456789012345", output.stderr)


if __name__ == "__main__":
    unittest.main()
