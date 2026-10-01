import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from quality_gates import (  # noqa: E402
    QualityGateError,
    execute_quality_gates,
    load_quality_gates,
    run_gate,
    run_with_optional_work_item,
)
from work_item_lifecycle import (  # noqa: E402
    InMemoryWorkItemProvider,
    LifecycleState,
    MutationEvidence,
    WorkItem,
 )


class UnverifiedMutationProvider(InMemoryWorkItemProvider):
    def __init__(self, items, unverified_operation):
        super().__init__(items)
        self.unverified_operation = unverified_operation

    def transition(self, *args, **kwargs):
        evidence = super().transition(*args, **kwargs)
        if self.unverified_operation == "transition":
            return MutationEvidence(
                provider=evidence.provider,
                operation=evidence.operation,
                work_item_id=evidence.work_item_id,
                state_before=evidence.state_before,
                state_after=evidence.state_after,
                verified=False,
                reference=evidence.reference,
                identifier=evidence.identifier,
            )
        return evidence

    def comment(self, *args, **kwargs):
        evidence = super().comment(*args, **kwargs)
        if self.unverified_operation == "comment":
            return MutationEvidence(
                provider=evidence.provider,
                operation=evidence.operation,
                work_item_id=evidence.work_item_id,
                state_before=evidence.state_before,
                state_after=evidence.state_after,
                verified=False,
                reference=evidence.reference,
                identifier=evidence.identifier,
            )
        return evidence

    def attach_traceability(self, *args, **kwargs):
        evidence = super().attach_traceability(*args, **kwargs)
        if self.unverified_operation == "traceability":
            return MutationEvidence(
                provider=evidence.provider,
                operation=evidence.operation,
                work_item_id=evidence.work_item_id,
                state_before=evidence.state_before,
                state_after=evidence.state_after,
                verified=False,
                reference=evidence.reference,
                identifier=evidence.identifier,
            )
        return evidence


class QualityGateTests(unittest.TestCase):
    def _write_manifest(self, root: Path, gates: list[dict]) -> Path:
        manifest = root / "quality-gates.json"
        manifest.write_text(
            json.dumps({"schema_version": 1, "gates": gates}),
            encoding="utf-8",
        )
        return manifest

    def test_manifest_preserves_declared_gate_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {
                        "id": "format",
                        "command": ["echo", "format"],
                        "required": True,
                    },
                    {
                        "id": "tests",
                        "command": ["echo", "tests"],
                        "required": True,
                    },
                ],
            )
            gates = load_quality_gates(manifest)
            self.assertEqual(["format", "tests"], [gate.id for gate in gates])

    def test_evidence_output_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [{"id": "tests", "command": ["echo", "ok"], "required": True}],
            )
            target = root / "external.json"
            target.write_text("protected\n", encoding="utf-8")
            output = root / "evidence.json"
            output.symlink_to(target)

            with self.assertRaisesRegex(
                QualityGateError,
                "must not be a symbolic link",
            ):
                run_with_optional_work_item(
                    root,
                    manifest,
                    evidence_path=output,
                    run_command=lambda command, **kwargs: subprocess.CompletedProcess(
                        command, 0, "ok\n", ""
                    ),
                )

            self.assertEqual("protected\n", target.read_text(encoding="utf-8"))

    def test_manifest_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "quality-gates.json"
            manifest.write_text(
                '{"schema_version":1,"schema_version":1,"gates":[]}',
                encoding="utf-8",
            )
            with self.assertRaises(QualityGateError):
                load_quality_gates(manifest)

    def test_manifest_requires_at_least_one_required_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {
                        "id": "optional-check",
                        "command": ["echo", "optional"],
                        "required": False,
                    }
                ],
            )
            with self.assertRaises(QualityGateError):
                load_quality_gates(manifest)

    def test_manifest_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {"id": "tests", "command": ["echo", "1"]},
                    {"id": "tests", "command": ["echo", "2"]},
                ],
            )
            with self.assertRaises(QualityGateError):
                load_quality_gates(manifest)

    def test_manifest_requires_argv_list_and_project_relative_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {"id": "shell", "command": "echo unsafe"},
                ],
            )
            with self.assertRaises(QualityGateError):
                load_quality_gates(manifest)

            manifest = self._write_manifest(
                root,
                [
                    {
                        "id": "escape",
                        "command": ["echo", "unsafe"],
                        "working_directory": "../outside",
                    }
                ],
            )
            with self.assertRaises(QualityGateError):
                load_quality_gates(manifest)

    def test_manifest_rejects_secret_like_environment_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {
                        "id": "tests",
                        "command": ["echo", "ok"],
                        "environment": {"API_TOKEN": "secret"},
                    }
                ],
            )
            with self.assertRaises(QualityGateError):
                load_quality_gates(manifest)

    def test_required_gate_failure_is_reported_and_optional_failure_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {
                        "id": "required-check",
                        "command": ["required"],
                        "required": True,
                    },
                    {
                        "id": "optional-check",
                        "command": ["optional"],
                        "required": False,
                    },
                ],
            )
            responses = {
                "required": subprocess.CompletedProcess(["required"], 2, "bad", "required failed"),
                "optional": subprocess.CompletedProcess(["optional"], 3, "", "optional failed"),
            }

            def runner(command, **kwargs):  # noqa: ANN001, ANN003
                return responses[command[0]]

            evidence = execute_quality_gates(
                root,
                manifest,
                run_command=runner,
            )
            self.assertEqual("failed", evidence.status)
            self.assertEqual(("required-check",), evidence.required_failures)
            self.assertEqual(
                ["failed", "failed"],
                [result.status for result in evidence.gates],
            )

    def test_gate_environment_excludes_inherited_credential_like_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate = load_quality_gates(
                self._write_manifest(
                    root,
                    [
                        {
                            "id": "environment",
                            "command": ["echo", "ok"],
                            "required": True,
                            "environment": {"SAFE_GATE_FLAG": "enabled"},
                        }
                    ],
                )
            )[0]

            captured: dict[str, str] = {}

            def runner(command, **kwargs):  # noqa: ANN001, ANN003
                captured.update(kwargs["env"])
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.dict(
                "quality_gates.os.environ",
                {
                    "GITHUB_TOKEN": "ghs_secret",
                    "NPM_TOKEN": "npm_secret",
                    "AWS_SECRET_ACCESS_KEY": "aws_secret",
                    "NPM_CONFIG__AUTH": "npm-auth-secret",
                    "SAFE_PARENT_FLAG": "present",
                },
                clear=True,
            ):
                result = run_gate(root, gate, run_command=runner)

            self.assertEqual("passed", result.status)
            self.assertNotIn("GITHUB_TOKEN", captured)
            self.assertNotIn("NPM_TOKEN", captured)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", captured)
            self.assertNotIn("NPM_CONFIG__AUTH", captured)
            self.assertEqual("present", captured["SAFE_PARENT_FLAG"])
            self.assertEqual("enabled", captured["SAFE_GATE_FLAG"])

    def test_output_and_environment_values_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate = load_quality_gates(
                self._write_manifest(
                    root,
                    [
                        {
                            "id": "redaction",
                            "command": ["echo", "ok"],
                            "required": True,
                        }
                    ],
                )
            )[0]

            def runner(command, **kwargs):  # noqa: ANN001, ANN003
                environment = kwargs["env"]
                environment["DEMO_SECRET"] = "secret-value"
                return subprocess.CompletedProcess(
                    command,
                    1,
                    "token=secret-value\nAuthorization: Bearer topsecret\n",
                    "",
                )

            with patch.dict("quality_gates.os.environ", {"DEMO_SECRET": "secret-value"}):
                result = run_gate(root, gate, run_command=runner)

            self.assertNotIn("secret-value", result.stdout)
            self.assertNotIn("topsecret", result.stdout)
            self.assertIn("[REDACTED]", result.stdout)

    def test_timeout_is_a_failed_gate_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gate = load_quality_gates(
                self._write_manifest(
                    root,
                    [
                        {
                            "id": "slow",
                            "command": ["slow"],
                            "required": True,
                            "timeout_seconds": 5,
                        }
                    ],
                )
            )[0]

            def runner(command, **kwargs):  # noqa: ANN001, ANN003
                raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

            result = run_gate(root, gate, run_command=runner)
            self.assertEqual("timed_out", result.status)
            self.assertTrue(result.timed_out)

    def test_success_synchronizes_verification_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {
                        "id": "tests",
                        "command": ["tests"],
                        "required": True,
                    }
                ],
            )
            provider = InMemoryWorkItemProvider(
                {
                    "58": WorkItem(
                        id="58",
                        title="quality",
                        state=LifecycleState.VERIFICATION,
                        provider="memory",
                    )
                }
            )

            def runner(command, **kwargs):  # noqa: ANN001, ANN003
                return subprocess.CompletedProcess(command, 0, "ok\n", "")

            evidence = run_with_optional_work_item(
                root,
                manifest,
                work_item_provider=provider,
                work_item_id="58",
                evidence_path=root / "quality-evidence.json",
                run_command=runner,
            )
            self.assertEqual(LifecycleState.REVIEW, provider.get("58").state)
            self.assertEqual("review", evidence["work_item"]["state_after_execution"])
            self.assertTrue((root / "quality-evidence.json").is_file())

    def test_required_failure_blocks_verification_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [
                    {
                        "id": "tests",
                        "command": ["tests"],
                        "required": True,
                    }
                ],
            )
            provider = InMemoryWorkItemProvider(
                {
                    "58": WorkItem(
                        id="58",
                        title="quality",
                        state=LifecycleState.VERIFICATION,
                        provider="memory",
                    )
                }
            )

            def runner(command, **kwargs):  # noqa: ANN001, ANN003
                return subprocess.CompletedProcess(command, 1, "", "failed")

            evidence = run_with_optional_work_item(
                root,
                manifest,
                work_item_provider=provider,
                work_item_id="58",
                run_command=runner,
            )
            self.assertEqual(LifecycleState.BLOCKED, provider.get("58").state)
            self.assertEqual("blocked", evidence["work_item"]["state_after_execution"])
            self.assertIn("tests", provider.comments["58"][-1])

    def test_success_fails_closed_on_unverified_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [{"id": "tests", "command": ["tests"], "required": True}],
            )
            provider = UnverifiedMutationProvider(
                {
                    "58": WorkItem(
                        id="58",
                        title="quality",
                        state=LifecycleState.VERIFICATION,
                        provider="memory",
                    )
                },
                "traceability",
            )

            with self.assertRaisesRegex(
                QualityGateError,
                "synchronization failed",
            ):
                run_with_optional_work_item(
                    root,
                    manifest,
                    work_item_provider=provider,
                    work_item_id="58",
                    evidence_path=root / "quality-evidence.json",
                    run_command=lambda command, **kwargs: subprocess.CompletedProcess(
                        command, 0, "ok\n", ""
                    ),
                )

            self.assertEqual(LifecycleState.VERIFICATION, provider.get("58").state)

    def test_success_fails_closed_on_unverified_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [{"id": "tests", "command": ["tests"], "required": True}],
            )
            provider = UnverifiedMutationProvider(
                {
                    "58": WorkItem(
                        id="58",
                        title="quality",
                        state=LifecycleState.VERIFICATION,
                        provider="memory",
                    )
                },
                "comment",
            )

            with self.assertRaisesRegex(
                QualityGateError,
                "synchronization failed",
            ):
                run_with_optional_work_item(
                    root,
                    manifest,
                    work_item_provider=provider,
                    work_item_id="58",
                    run_command=lambda command, **kwargs: subprocess.CompletedProcess(
                        command, 0, "ok\n", ""
                    ),
                )

            self.assertEqual(LifecycleState.VERIFICATION, provider.get("58").state)

    def test_success_fails_closed_on_unverified_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [{"id": "tests", "command": ["tests"], "required": True}],
            )
            provider = UnverifiedMutationProvider(
                {
                    "58": WorkItem(
                        id="58",
                        title="quality",
                        state=LifecycleState.VERIFICATION,
                        provider="memory",
                    )
                },
                "transition",
            )

            with self.assertRaisesRegex(
                QualityGateError,
                "synchronization failed",
            ):
                run_with_optional_work_item(
                    root,
                    manifest,
                    work_item_provider=provider,
                    work_item_id="58",
                    run_command=lambda command, **kwargs: subprocess.CompletedProcess(
                        command, 0, "ok\n", ""
                    ),
                )

            self.assertEqual(LifecycleState.REVIEW, provider.get("58").state)

    def test_failure_fails_closed_on_unverified_block_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [{"id": "tests", "command": ["tests"], "required": True}],
            )
            provider = UnverifiedMutationProvider(
                {
                    "58": WorkItem(
                        id="58",
                        title="quality",
                        state=LifecycleState.VERIFICATION,
                        provider="memory",
                    )
                },
                "transition",
            )

            with self.assertRaisesRegex(
                QualityGateError,
                "work-item synchronization also failed",
            ):
                run_with_optional_work_item(
                    root,
                    manifest,
                    work_item_provider=provider,
                    work_item_id="58",
                    run_command=lambda command, **kwargs: subprocess.CompletedProcess(
                        command, 1, "", "failed"
                    ),
                )

            self.assertEqual(LifecycleState.BLOCKED, provider.get("58").state)

    def test_provider_requires_verification_state_before_running_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(
                root,
                [{"id": "tests", "command": ["tests"], "required": True}],
            )
            provider = InMemoryWorkItemProvider(
                {
                    "58": WorkItem(
                        id="58",
                        title="quality",
                        state=LifecycleState.IN_PROGRESS,
                        provider="memory",
                    )
                }
            )
            with self.assertRaises(QualityGateError):
                run_with_optional_work_item(
                    root,
                    manifest,
                    work_item_provider=provider,
                    work_item_id="58",
                )


if __name__ == "__main__":
    unittest.main()
