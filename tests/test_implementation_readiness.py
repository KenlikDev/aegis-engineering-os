import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_bundle import build_evidence_bundle, write_evidence_bundle  # noqa: E402
from evidence_contract import build_evidence, read_and_validate_evidence, write_evidence  # noqa: E402
from implementation_readiness import (  # noqa: E402
    ImplementationReadinessError,
    evaluate_readiness,
)
from version_verification import record_version_evidence  # noqa: E402
from work_item_lifecycle import InMemoryWorkItemProvider, LifecycleState, WorkItem  # noqa: E402


WORK_ITEM = """# Work Item

## Identity

Provider: memory
Work item ID: 106
Title: Validate implementation readiness

## Intent

The implementation must start only after its explicit engineering prerequisites are verified.

## Scope

### In scope

- readiness evidence validation

### Out of scope

- product behavior changes

## Acceptance criteria

- [ ] The readiness gate returns deterministic evidence.

## Dependencies

- Python runtime

## Roles

Primary role: software engineer

## Technical notes

Affected component: tools/implementation_readiness.py
Existing project contracts must remain authoritative.

## Risks

- Missing evidence could permit unsafe implementation.

## Verification plan

- Run the Aegis policy test suite.

## Delivery links

Branch:
Pull request:
Documentation:
ADR:

## Status log

Ready for implementation readiness evaluation.

## Definition of done

- [ ] Acceptance criteria satisfied
"""


class ImplementationReadinessTests(unittest.TestCase):
    def _fixture(self, *, ready: bool = True):
        project = tempfile.TemporaryDirectory()
        root = Path(project.name)
        work_item = root / "work-item.md"
        work_item.write_text(WORK_ITEM, encoding="utf-8")
        claims = root / "version-claims.json"
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "python",
                            "version": "3.13",
                            "scope": "language",
                            "source": "version-source.txt",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "version-source.txt").write_text(
            "Python 3.13 toolchain evidence.\n",
            encoding="utf-8",
        )
        evidence = root / ".aegis" / "version-evidence.json"
        evidence.parent.mkdir()
        record_version_evidence(root, claims, evidence)
        provider = InMemoryWorkItemProvider(
            {
                "106": WorkItem(
                    id="106",
                    title="Validate implementation readiness",
                    state=LifecycleState.READY if ready else LifecycleState.PLANNED,
                    provider="memory",
                )
            }
        )
        self.addCleanup(project.cleanup)
        return root, work_item, evidence, provider

    def _evidence_set(self, root: Path, revision: str = "7c2d2247abf2d4463a2167d20e7ab18a808a24ee"):
        evidence_path = root / ".aegis" / "input-evidence.json"
        write_evidence(
            build_evidence(
                {
                    "schema_version": 1,
                    "kind": "testing",
                    "source": "aegis:testing",
                    "subject": "project-testing",
                    "revision": revision,
                    "observed_at": "2026-09-28T18:00:00Z",
                    "status": "verified",
                    "result": {"state": "passed"},
                    "uncertainty": [],
                    "references": [],
                    "artifact_sha256": None,
                }
            ),
            evidence_path,
        )
        self.assertEqual(
            "verified",
            read_and_validate_evidence(evidence_path).status,
        )

        bundle_path = root / ".aegis" / "readiness-bundle.json"
        bundle = build_evidence_bundle(
            root,
            "Explicit readiness evidence",
            [evidence_path],
        )
        write_evidence_bundle(bundle, root, bundle_path)

        requirements_path = root / ".aegis" / "readiness-requirements.json"
        requirements_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "requirements": [
                        {
                            "kind": "testing",
                            "status": "verified",
                            "subject": "project-testing",
                            "source": "aegis:testing",
                            "revision": revision,
                        }
                    ],
                    "allow_extra_members": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return bundle_path, requirements_path


    def test_cli_can_emit_canonical_readiness_evidence(self):
        root, work_item, evidence, _ = self._fixture()
        canonical = root / ".aegis" / "implementation-readiness-evidence.json"
        bundle, requirements = self._evidence_set(root)

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "implementation_readiness.py"),
                str(work_item),
                "--project-root",
                str(root),
                "--kind",
                "feature",
                "--version-evidence-ref",
                str(evidence),
                "--architecture-not-required",
                "--evidence-bundle",
                str(bundle),
                "--evidence-set-requirements",
                str(requirements),
                "--evidence-output",
                str(canonical),
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn('"ready": true', completed.stdout)
        payload = json.loads(canonical.read_text(encoding="utf-8"))
        self.assertEqual("implementation-readiness", payload["kind"])
        self.assertEqual("work-item:unspecified", payload["subject"])
        self.assertEqual("verified", payload["status"])
        self.assertEqual([], payload["uncertainty"])
        self.assertEqual(
            "feature",
            payload["result"]["work_item_kind"],
        )
        self.assertEqual("verified", payload["result"]["evidence_set"]["status"])
        self.assertEqual(1, payload["result"]["evidence_set"]["requirements_satisfied"])
        bundle_payload = json.loads(bundle.read_text(encoding="utf-8"))
        self.assertEqual(
            bundle_payload["bundle_id"],
            payload["result"]["evidence_set"]["bundle_id"],
        )
        canonical_record = read_and_validate_evidence(canonical)
        self.assertEqual(
            payload["result"]["evidence_set"]["bundle_id"],
            canonical_record.result["evidence_set"]["bundle_id"],
        )

    def test_explicit_evidence_set_is_a_readiness_prerequisite(self):
        root, work_item, evidence, provider = self._fixture()
        bundle, requirements = self._evidence_set(root)

        result = evaluate_readiness(
            work_item,
            "feature",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=False,
            work_item_provider=provider,
            work_item_id="106",
            evidence_bundle_ref=bundle,
            evidence_set_requirements_ref=requirements,
        )

        self.assertTrue(result.ready)
        self.assertIsNotNone(result.evidence_set)
        assert result.evidence_set is not None
        self.assertEqual("verified", result.evidence_set.status)
        self.assertEqual(1, result.evidence_set.requirements_satisfied)
        self.assertIn(
            "evidence-set",
            {item.check for item in result.observations},
        )

    def test_evidence_set_revision_mismatch_blocks_readiness(self):
        root, work_item, evidence, provider = self._fixture()
        bundle, requirements = self._evidence_set(root)
        payload = json.loads(requirements.read_text(encoding="utf-8"))
        payload["requirements"][0]["revision"] = "a" * 40
        requirements.write_text(json.dumps(payload), encoding="utf-8")

        result = evaluate_readiness(
            work_item,
            "feature",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=False,
            work_item_provider=provider,
            work_item_id="106",
            evidence_bundle_ref=bundle,
            evidence_set_requirements_ref=requirements,
        )

        self.assertFalse(result.ready)
        self.assertIsNotNone(result.evidence_set)
        assert result.evidence_set is not None
        self.assertEqual("blocked", result.evidence_set.status)
        self.assertIn(
            "Explicit evidence-set requirements are not satisfied.",
            result.blockers,
        )

    def test_evidence_set_inputs_must_be_supplied_together(self):
        root, work_item, evidence, provider = self._fixture()
        bundle, _ = self._evidence_set(root)

        with self.assertRaisesRegex(
            ImplementationReadinessError,
            "must be provided together",
        ):
            evaluate_readiness(
                work_item,
                "feature",
                project_root=root,
                version_evidence_ref=evidence,
                architecture_required=False,
                work_item_provider=provider,
                work_item_id="106",
                evidence_bundle_ref=bundle,
            )

    def test_cli_refuses_to_overwrite_version_evidence(self):
        root, work_item, evidence, _ = self._fixture()
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "implementation_readiness.py"),
                str(work_item),
                "--project-root",
                str(root),
                "--kind",
                "feature",
                "--version-evidence-ref",
                str(evidence),
                "--architecture-not-required",
                "--evidence-output",
                str(evidence),
            ],
            text=True,
            capture_output=True,
        )

        self.assertEqual(1, completed.returncode)
        self.assertIn("must not overwrite", completed.stderr)

    def test_cli_refuses_to_overwrite_evidence_set_inputs(self):
        root, work_item, evidence, _ = self._fixture()
        bundle, requirements = self._evidence_set(root)

        for protected in (bundle, requirements):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "implementation_readiness.py"),
                    str(work_item),
                    "--project-root",
                    str(root),
                    "--kind",
                    "feature",
                    "--version-evidence-ref",
                    str(evidence),
                    "--architecture-not-required",
                    "--evidence-bundle",
                    str(bundle),
                    "--evidence-set-requirements",
                    str(requirements),
                    "--evidence-output",
                    str(protected),
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual(1, completed.returncode)
            self.assertIn("must not overwrite", completed.stderr)


    def test_ready_with_explicit_architecture_plan(self):
        root, work_item, evidence, provider = self._fixture()
        result = evaluate_readiness(
            work_item,
            "refactoring",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=True,
            work_item_provider=provider,
            work_item_id="106",
        )
        self.assertTrue(result.ready)
        self.assertEqual("ready", result.requirements_status)
        self.assertEqual("ready", result.lifecycle_state)
        self.assertIn("refactoring", result.composition_steps)
        self.assertIn("version-verification", result.composition_steps)
        self.assertIn("passed", {item.status for item in result.observations})

    def test_pending_external_version_check_remains_visible(self):
        root, work_item, evidence, provider = self._fixture()
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        payload["external_verification_pending"] = True
        evidence.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result = evaluate_readiness(
            work_item,
            "feature",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=False,
            work_item_provider=provider,
            work_item_id="106",
        )
        self.assertTrue(result.ready)
        self.assertTrue(result.version_external_verification_pending)
        version = next(
            item for item in result.observations if item.check == "version-verification"
        )
        self.assertEqual("pending", version.status)

    def test_architecture_required_works_without_lifecycle_provider(self):
        root, work_item, evidence, _ = self._fixture()
        result = evaluate_readiness(
            work_item,
            "feature",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=True,
            work_item_id="106",
        )
        self.assertTrue(result.ready)
        self.assertEqual("passed", next(item.status for item in result.observations if item.check == "architecture"))

    def test_architecture_not_required_is_explicit_and_does_not_block(self):
        root, work_item, evidence, provider = self._fixture()
        result = evaluate_readiness(
            work_item,
            "feature",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=False,
            work_item_provider=provider,
            work_item_id="106",
        )
        self.assertTrue(result.ready)
        architecture = next(item for item in result.observations if item.check == "architecture")
        self.assertEqual("not-required", architecture.status)

    def test_blocked_requirements_prevent_architecture_readiness(self):
        root, work_item, evidence, provider = self._fixture()
        broken = work_item.read_text(encoding="utf-8").replace(
            "### Out of scope\n\n- product behavior changes",
            "### Out of scope\n\n- ...",
        )
        work_item.write_text(broken, encoding="utf-8")
        result = evaluate_readiness(
            work_item,
            "feature",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=True,
            work_item_provider=provider,
            work_item_id="106",
        )
        self.assertFalse(result.ready)
        self.assertGreaterEqual(len(result.blockers), 2)
        self.assertTrue(any(item.check == "architecture" and item.status == "blocked" for item in result.observations))

    def test_empty_local_version_evidence_is_rejected(self):
        root, work_item, evidence, provider = self._fixture()
        evidence.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ImplementationReadinessError, "JSON"):
            evaluate_readiness(
                work_item,
                "feature",
                project_root=root,
                version_evidence_ref=evidence,
                architecture_required=False,
                work_item_provider=provider,
                work_item_id="106",
            )

    def test_version_evidence_cannot_escape_project_root(self):
        root, work_item, _, provider = self._fixture()
        outside = root.parent / "version-evidence.txt"
        outside.write_text("external", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        with self.assertRaisesRegex(ImplementationReadinessError, "inside the project root"):
            evaluate_readiness(
                work_item,
                "feature",
                project_root=root,
                version_evidence_ref=outside,
                architecture_required=False,
                work_item_provider=provider,
                work_item_id="106",
            )

    def test_legacy_text_version_evidence_is_rejected(self):
        root, work_item, _, provider = self._fixture()
        legacy = root / "legacy-version.txt"
        legacy.write_text("Python 3.13", encoding="utf-8")
        with self.assertRaisesRegex(ImplementationReadinessError, "JSON"):
            evaluate_readiness(
                work_item,
                "feature",
                project_root=root,
                version_evidence_ref=legacy,
                architecture_required=False,
                work_item_provider=provider,
                work_item_id="106",
            )

    def test_external_version_reference_is_not_verified(self):
        root, work_item, _, provider = self._fixture()
        with self.assertRaisesRegex(ImplementationReadinessError, "local schema-validated"):
            evaluate_readiness(
                work_item,
                "feature",
                project_root=root,
                version_evidence_ref="https://example.invalid/toolchain.txt",
                architecture_required=False,
                work_item_provider=provider,
                work_item_id="106",
            )

    def test_work_item_document_id_must_match_provider_id(self):
        root, work_item, evidence, provider = self._fixture()
        work_item.write_text(
            work_item.read_text(encoding="utf-8").replace(
                "Work item ID: 106",
                "Work item ID: 999",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ImplementationReadinessError, "does not match"):
            evaluate_readiness(
                work_item,
                "feature",
                project_root=root,
                version_evidence_ref=evidence,
                architecture_required=False,
                work_item_provider=provider,
                work_item_id="106",
            )

    def test_lifecycle_must_be_ready_when_provider_is_supplied(self):
        root, work_item, evidence, provider = self._fixture(ready=False)
        with self.assertRaisesRegex(ImplementationReadinessError, "ready work item"):
            evaluate_readiness(
                work_item,
                "feature",
                project_root=root,
                version_evidence_ref=evidence,
                architecture_required=False,
                work_item_provider=provider,
                work_item_id="106",
            )

    def test_evaluation_does_not_mutate_work_item(self):
        root, work_item, evidence, provider = self._fixture()
        before = work_item.read_bytes()
        first = evaluate_readiness(
            work_item,
            "bug-fix",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=False,
            work_item_provider=provider,
            work_item_id="106",
        )
        second = evaluate_readiness(
            work_item,
            "bug-fix",
            project_root=root,
            version_evidence_ref=evidence,
            architecture_required=False,
            work_item_provider=provider,
            work_item_id="106",
        )
        self.assertEqual(before, work_item.read_bytes())
        self.assertEqual(first, second)
        self.assertEqual(LifecycleState.READY, provider.get("106").state)


if __name__ == "__main__":
    unittest.main()
