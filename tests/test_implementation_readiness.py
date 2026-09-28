import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from implementation_readiness import (  # noqa: E402
    ImplementationReadinessError,
    evaluate_readiness,
)
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
        evidence = root / "version-evidence.txt"
        evidence.write_text("Python 3.13; project toolchain verified.\n", encoding="utf-8")
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
        with self.assertRaisesRegex(ImplementationReadinessError, "empty"):
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

    def test_external_version_reference_is_not_verified(self):
        root, work_item, _, provider = self._fixture()
        result = evaluate_readiness(
            work_item,
            "feature",
            project_root=root,
            version_evidence_ref="https://example.invalid/toolchain.txt",
            architecture_required=False,
            work_item_provider=provider,
            work_item_id="106",
        )
        self.assertFalse(result.ready)
        version = next(
            item for item in result.observations if item.check == "version-verification"
        )
        self.assertEqual("blocked", version.status)

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
