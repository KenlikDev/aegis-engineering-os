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
    WorkItem,
)


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
